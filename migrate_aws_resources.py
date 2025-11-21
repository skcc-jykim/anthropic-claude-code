#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import tempfile
import json
import requests
import boto3
import logging
import time
from botocore.exceptions import ClientError
from typing import Optional, Dict, List, Tuple

# ===================================================
# 로깅 설정
# ===================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ===================================================
# 설정
# ===================================================
SRC_PROFILE = os.getenv("SRC_PROFILE", "src")
DST_PROFILE = os.getenv("DST_PROFILE", "dst")
REGION = os.getenv("AWS_REGION", "ap-northeast-2")
NAME_PREFIX = os.getenv("NAME_PREFIX", "")

# 매핑에 없으면 이 Role 적용
DEFAULT_DEST_LAMBDA_ROLE = os.getenv(
    "DEFAULT_DEST_LAMBDA_ROLE",
    "arn:aws:iam::846697434179:role/skies-dp-prd-dip-lambda-default-role"
)

DEFAULT_DEST_SFN_ROLE = os.getenv(
    "DEFAULT_DEST_SFN_ROLE",
    "arn:aws:iam::846697434179:role/skies-dp-prd-dip-sfn-default-role"
)

# 서브넷 매핑
SUBNET_MAP = {
    "subnet-0b08f7b5e2f07cad8": "subnet-022ded0a08e1dbc9a",
    "subnet-05aeed41c8cb4080e": "subnet-00881d195d89d74e3"
}

# SG 매핑
SG_MAP = {
    "sg-0700c496945e95799": "sg-02cb6834543c0da58",
}

# IAM Role 매핑 (필요시 확장)
ROLE_MAP: Dict[str, str] = {}

# 동적으로 채워질 매핑
LAYER_MAP: Dict[str, str] = {}
LAMBDA_ARN_MAP: Dict[str, str] = {}  # 소스 ARN -> 대상 ARN
SFN_ARN_MAP: Dict[str, str] = {}  # 소스 ARN -> 대상 ARN

# 재시도 설정
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


# ===================================================
# 유틸 함수
# ===================================================

def retry_on_throttle(func):
    """API throttling 시 재시도 데코레이터"""
    def wrapper(*args, **kwargs):
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except ClientError as e:
                error_code = e.response['Error']['Code']
                if error_code in ['TooManyRequestsException', 'ThrottlingException', 'RequestLimitExceeded']:
                    if attempt < MAX_RETRIES - 1:
                        wait_time = RETRY_DELAY * (2 ** attempt)
                        logger.warning(f"Throttled. Retrying in {wait_time}s... (attempt {attempt + 1}/{MAX_RETRIES})")
                        time.sleep(wait_time)
                    else:
                        raise
                else:
                    raise
    return wrapper


def download_code(code_url: str, dest_path: str):
    """Lambda/Layer 코드 다운로드"""
    r = requests.get(code_url, stream=True, timeout=300)
    r.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)


def map_vpc_config(vpc_cfg: Optional[dict]) -> Optional[dict]:
    """VPC 설정 매핑"""
    if not vpc_cfg or not vpc_cfg.get("SubnetIds"):
        return None
    return {
        "SubnetIds": [SUBNET_MAP.get(s, s) for s in vpc_cfg.get("SubnetIds", [])],
        "SecurityGroupIds": [SG_MAP.get(sg, sg) for sg in vpc_cfg.get("SecurityGroupIds", [])]
    }


def map_role(role_arn: str, resource_type: str = "lambda") -> str:
    """IAM Role 매핑"""
    # 명시적 매핑이 있으면 사용
    if role_arn in ROLE_MAP:
        return ROLE_MAP[role_arn]

    # 기본 Role 사용
    if resource_type == "sfn":
        return DEFAULT_DEST_SFN_ROLE
    return DEFAULT_DEST_LAMBDA_ROLE


def extract_account_from_arn(arn: str) -> Optional[str]:
    """ARN에서 계정 ID 추출"""
    parts = arn.split(":")
    if len(parts) >= 5:
        return parts[4]
    return None


def is_valid_arn(arn: str) -> bool:
    """ARN 유효성 검증"""
    if not arn or not isinstance(arn, str):
        return False

    parts = arn.split(":")
    # ARN은 최소한 arn:partition:service:region:account-id:resource 형식이어야 함
    if len(parts) < 6:
        return False

    # 첫 번째 부분은 "arn"이어야 함
    if parts[0] != "arn":
        return False

    # 계정 ID는 비어있지 않아야 함 (일부 서비스는 예외지만 Lambda/StepFunctions는 필수)
    account_id = parts[4]
    if not account_id:
        return False

    # 리소스 부분이 있어야 함
    if len(parts) < 6 or not parts[5]:
        return False

    return True


def replace_lambda_arns_in_definition(definition: dict, src_account: str, dst_account: str) -> dict:
    """
    StepFunction 정의에서 Lambda ARN을 재귀적으로 교체
    """
    if isinstance(definition, dict):
        new_dict = {}
        for key, value in definition.items():
            if key == "Resource" and isinstance(value, str):
                # Lambda ARN 교체
                if "arn:aws:lambda" in value and src_account in value:
                    # LAMBDA_ARN_MAP에서 찾기
                    mapped = LAMBDA_ARN_MAP.get(value)
                    if mapped:
                        new_dict[key] = mapped
                        logger.info(f"  Replaced Lambda ARN: {value} -> {mapped}")
                    else:
                        # 계정 ID만 교체
                        new_dict[key] = value.replace(src_account, dst_account)
                        logger.warning(f"  No mapping found, replaced account ID: {value} -> {new_dict[key]}")
                else:
                    new_dict[key] = value
            else:
                new_dict[key] = replace_lambda_arns_in_definition(value, src_account, dst_account)
        return new_dict
    elif isinstance(definition, list):
        return [replace_lambda_arns_in_definition(item, src_account, dst_account) for item in definition]
    else:
        return definition


# ===================================================
# Layer 자동 마이그레이션
# ===================================================
@retry_on_throttle
def migrate_layers(lambda_src, lambda_dst):
    """모든 Layer를 자동으로 계정 간 복제하고 LAYER_MAP 자동 구성"""

    logger.info("\n" + "="*50)
    logger.info("🔧 Layer 자동 마이그레이션 시작")
    logger.info("="*50)

    paginator = lambda_src.get_paginator("list_layers")

    with tempfile.TemporaryDirectory() as tmpdir:
        for page in paginator.paginate():
            for layer in page.get("Layers", []):
                layer_name = layer["LayerName"]
                logger.info(f"\n➡ Layer 처리 중: {layer_name}")

                versions = lambda_src.list_layer_versions(LayerName=layer_name)["LayerVersions"]

                for v in versions:
                    src_arn = v["LayerVersionArn"]
                    version_number = v["Version"]

                    # 이미 매핑된 경우 skip
                    if src_arn in LAYER_MAP:
                        continue

                    # Layer ZIP 다운로드
                    layer_detail = lambda_src.get_layer_version(
                        LayerName=layer_name,
                        VersionNumber=version_number
                    )

                    code_url = layer_detail["Content"]["Location"]
                    zip_path = os.path.join(tmpdir, f"{layer_name}-{version_number}.zip")

                    logger.info(f"  다운로드 중: {layer_name}:{version_number}")
                    download_code(code_url, zip_path)

                    # 대상 계정에 Layer 버전 존재하는지 확인
                    dst_versions = []
                    try:
                        dst_versions = lambda_dst.list_layer_versions(LayerName=layer_name).get("LayerVersions", [])
                    except ClientError:
                        dst_versions = []

                    dst_arn = None

                    for dv in dst_versions:
                        if dv["Version"] == version_number:
                            dst_arn = dv["LayerVersionArn"]
                            logger.info(f"  대상에 이미 존재: {dst_arn}")
                            break

                    # 대상 계정에 없으면 생성
                    if not dst_arn:
                        logger.info(f"  생성 중: {layer_name}:{version_number}")
                        with open(zip_path, "rb") as f:
                            content = f.read()

                        resp = lambda_dst.publish_layer_version(
                            LayerName=layer_name,
                            Content={"ZipFile": content},
                            CompatibleRuntimes=layer_detail.get("CompatibleRuntimes", []),
                            CompatibleArchitectures=layer_detail.get("CompatibleArchitectures", [])
                        )
                        dst_arn = resp["LayerVersionArn"]

                    # 매핑 테이블에 등록
                    LAYER_MAP[src_arn] = dst_arn
                    logger.info(f"  ✔ 매핑 등록: {src_arn} -> {dst_arn}")

    logger.info(f"\n🔧 Layer 마이그레이션 완료! (총 {len(LAYER_MAP)}개)")


# ===================================================
# Lambda 마이그레이션 본체
# ===================================================
@retry_on_throttle
def migrate_lambdas(lambda_src, lambda_dst, src_account: str, dst_account: str):
    """Lambda 함수 마이그레이션 (태그, 동시성, DLQ 포함)"""

    logger.info("\n" + "="*50)
    logger.info("🚀 Lambda 함수 마이그레이션 시작")
    logger.info("="*50)

    paginator = lambda_src.get_paginator("list_functions")

    for page in paginator.paginate():
        for fn in page["Functions"]:
            name = fn["FunctionName"]

            if NAME_PREFIX and not name.startswith(NAME_PREFIX):
                continue

            logger.info(f"\n{'='*50}")
            logger.info(f"🔄 마이그레이션 중: {name}")
            logger.info(f"{'='*50}")

            try:
                cfg = lambda_src.get_function_configuration(FunctionName=name)
                code_info = lambda_src.get_function(FunctionName=name)["Code"]

                if cfg.get("PackageType") == "Image":
                    logger.warning(f"[SKIP] {name} (Container 이미지 Lambda는 지원 안함)")
                    continue

                # Lambda 코드 ZIP
                zip_url = code_info["Location"]
                with tempfile.TemporaryDirectory() as tmpdir:
                    zip_path = os.path.join(tmpdir, f"{name}.zip")
                    download_code(zip_url, zip_path)
                    with open(zip_path, "rb") as f:
                        zip_bytes = f.read()

                # base parameters
                params = {
                    "FunctionName": name,
                    "Role": map_role(cfg["Role"]),
                    "Runtime": cfg["Runtime"],
                    "Handler": cfg["Handler"],
                    "Timeout": cfg["Timeout"],
                    "MemorySize": cfg["MemorySize"],
                    "Architectures": cfg.get("Architectures", ["x86_64"]),
                    "Description": cfg.get("Description", "")
                }

                # Environment
                if cfg.get("Environment"):
                    params["Environment"] = cfg["Environment"]

                # Layers → 자동 매핑된 LAYER_MAP 사용
                if cfg.get("Layers"):
                    mapped = []
                    for layer in cfg["Layers"]:
                        src_arn = layer["Arn"]
                        dst_arn = LAYER_MAP.get(src_arn)
                        if not dst_arn:
                            logger.warning(f"  [WARN] Layer 매핑 없음 -> {src_arn} (원본 유지)")
                            mapped.append(src_arn)
                        else:
                            mapped.append(dst_arn)
                    params["Layers"] = mapped

                # VPC
                vpc_cfg = map_vpc_config(cfg.get("VpcConfig"))
                if vpc_cfg:
                    params["VpcConfig"] = vpc_cfg

                # Dead Letter Queue
                if cfg.get("DeadLetterConfig") and cfg["DeadLetterConfig"].get("TargetArn"):
                    dlq_arn = cfg["DeadLetterConfig"]["TargetArn"]
                    # DLQ ARN도 계정 변경 필요
                    params["DeadLetterConfig"] = {
                        "TargetArn": dlq_arn.replace(src_account, dst_account)
                    }

                # Lambda 생성/업데이트
                function_exists = False
                try:
                    lambda_dst.get_function(FunctionName=name)
                    function_exists = True
                except ClientError as e:
                    if e.response["Error"]["Code"] != "ResourceNotFoundException":
                        raise

                if function_exists:
                    logger.info(f"  기존 함수 업데이트 중...")
                    lambda_dst.update_function_configuration(**params)
                    time.sleep(1)  # Configuration 업데이트 완료 대기
                    lambda_dst.update_function_code(FunctionName=name, ZipFile=zip_bytes)
                    logger.info(f"  ✔ 업데이트 완료: {name}")
                else:
                    logger.info(f"  새 함수 생성 중...")
                    lambda_dst.create_function(**params, Code={"ZipFile": zip_bytes})
                    logger.info(f"  ✔ 생성 완료: {name}")

                # 함수 ARN 매핑 저장
                src_arn = cfg["FunctionArn"]
                dst_fn = lambda_dst.get_function_configuration(FunctionName=name)
                dst_arn = dst_fn["FunctionArn"]
                LAMBDA_ARN_MAP[src_arn] = dst_arn

                # 태그 복제
                try:
                    tags_response = lambda_src.list_tags(Resource=src_arn)
                    if tags_response.get("Tags"):
                        lambda_dst.tag_resource(Resource=dst_arn, Tags=tags_response["Tags"])
                        logger.info(f"  ✔ 태그 복제 완료 ({len(tags_response['Tags'])}개)")
                except ClientError as e:
                    logger.warning(f"  [WARN] 태그 복제 실패: {e}")

                # 예약 동시성 설정
                try:
                    concurrency = cfg.get("ReservedConcurrentExecutions")
                    if concurrency:
                        lambda_dst.put_function_concurrency(
                            FunctionName=name,
                            ReservedConcurrentExecutions=concurrency
                        )
                        logger.info(f"  ✔ 예약 동시성 설정 완료: {concurrency}")
                except ClientError as e:
                    logger.warning(f"  [WARN] 동시성 설정 실패: {e}")

            except Exception as e:
                logger.error(f"  ❌ 오류 발생: {name} - {e}")
                continue

    logger.info(f"\n🚀 Lambda 마이그레이션 완료! (총 {len(LAMBDA_ARN_MAP)}개)")


# ===================================================
# StepFunction 마이그레이션
# ===================================================
@retry_on_throttle
def migrate_step_functions(sfn_src, sfn_dst, src_account: str, dst_account: str):
    """Step Functions 상태 머신 마이그레이션"""

    logger.info("\n" + "="*50)
    logger.info("⚙️ Step Functions 마이그레이션 시작")
    logger.info("="*50)

    paginator = sfn_src.get_paginator("list_state_machines")

    for page in paginator.paginate():
        for sm in page.get("stateMachines", []):
            sm_name = sm["name"]
            src_arn = sm["stateMachineArn"]

            if NAME_PREFIX and not sm_name.startswith(NAME_PREFIX):
                continue

            logger.info(f"\n{'='*50}")
            logger.info(f"🔄 상태 머신 마이그레이션 중: {sm_name}")
            logger.info(f"{'='*50}")

            try:
                # 상태 머신 상세 정보 가져오기
                sm_detail = sfn_src.describe_state_machine(stateMachineArn=src_arn)

                # 정의에서 Lambda ARN 교체
                definition = json.loads(sm_detail["definition"])
                updated_definition = replace_lambda_arns_in_definition(definition, src_account, dst_account)

                # 생성 파라미터
                params = {
                    "name": sm_name,
                    "definition": json.dumps(updated_definition, ensure_ascii=False),
                    "roleArn": map_role(sm_detail["roleArn"], "sfn"),
                    "type": sm_detail.get("type", "STANDARD")
                }

                # Logging 설정
                if sm_detail.get("loggingConfiguration"):
                    params["loggingConfiguration"] = sm_detail["loggingConfiguration"]

                # Tracing 설정
                if sm_detail.get("tracingConfiguration"):
                    params["tracingConfiguration"] = sm_detail["tracingConfiguration"]

                # 상태 머신 생성/업데이트
                try:
                    # 기존 상태 머신 확인
                    dst_sm_list = sfn_dst.list_state_machines()
                    existing_sm = None
                    for existing in dst_sm_list.get("stateMachines", []):
                        if existing["name"] == sm_name:
                            existing_sm = existing
                            break

                    if existing_sm:
                        logger.info(f"  기존 상태 머신 업데이트 중...")
                        sfn_dst.update_state_machine(
                            stateMachineArn=existing_sm["stateMachineArn"],
                            definition=params["definition"],
                            roleArn=params["roleArn"],
                            loggingConfiguration=params.get("loggingConfiguration", {}),
                            tracingConfiguration=params.get("tracingConfiguration", {})
                        )
                        dst_arn = existing_sm["stateMachineArn"]
                        logger.info(f"  ✔ 업데이트 완료: {sm_name}")
                    else:
                        logger.info(f"  새 상태 머신 생성 중...")
                        response = sfn_dst.create_state_machine(**params)
                        dst_arn = response["stateMachineArn"]
                        logger.info(f"  ✔ 생성 완료: {sm_name}")

                    # ARN 매핑 저장
                    SFN_ARN_MAP[src_arn] = dst_arn

                    # 태그 복제
                    try:
                        tags_response = sfn_src.list_tags_for_resource(resourceArn=src_arn)
                        if tags_response.get("tags"):
                            sfn_dst.tag_resource(
                                resourceArn=dst_arn,
                                tags=tags_response["tags"]
                            )
                            logger.info(f"  ✔ 태그 복제 완료 ({len(tags_response['tags'])}개)")
                    except ClientError as e:
                        logger.warning(f"  [WARN] 태그 복제 실패: {e}")

                except ClientError as e:
                    logger.error(f"  ❌ 생성/업데이트 실패: {e}")
                    continue

            except Exception as e:
                logger.error(f"  ❌ 오류 발생: {sm_name} - {e}")
                continue

    logger.info(f"\n⚙️ Step Functions 마이그레이션 완료! (총 {len(SFN_ARN_MAP)}개)")


# ===================================================
# EventBridge 규칙 마이그레이션
# ===================================================
@retry_on_throttle
def migrate_eventbridge_rules(events_src, events_dst, src_account: str, dst_account: str):
    """EventBridge 규칙 및 스케줄 마이그레이션"""

    logger.info("\n" + "="*50)
    logger.info("📅 EventBridge 규칙 마이그레이션 시작")
    logger.info("="*50)

    # 기본 이벤트 버스의 규칙만 마이그레이션 (커스텀 버스는 별도 처리 필요)
    event_buses = ["default"]

    for bus_name in event_buses:
        logger.info(f"\n이벤트 버스: {bus_name}")

        paginator = events_src.get_paginator("list_rules")

        for page in paginator.paginate(EventBusName=bus_name):
            for rule in page.get("Rules", []):
                rule_name = rule["Name"]

                if NAME_PREFIX and not rule_name.startswith(NAME_PREFIX):
                    continue

                logger.info(f"\n{'='*50}")
                logger.info(f"🔄 규칙 마이그레이션 중: {rule_name}")
                logger.info(f"{'='*50}")

                try:
                    # 규칙 생성/업데이트
                    params = {
                        "Name": rule_name,
                        "State": rule.get("State", "ENABLED"),
                        "EventBusName": bus_name
                    }

                    if rule.get("ScheduleExpression"):
                        params["ScheduleExpression"] = rule["ScheduleExpression"]
                        logger.info(f"  스케줄: {rule['ScheduleExpression']}")

                    if rule.get("EventPattern"):
                        params["EventPattern"] = rule["EventPattern"]

                    if rule.get("Description"):
                        params["Description"] = rule["Description"]

                    if rule.get("RoleArn"):
                        params["RoleArn"] = map_role(rule["RoleArn"])

                    events_dst.put_rule(**params)
                    logger.info(f"  ✔ 규칙 생성/업데이트 완료")

                    # 타겟 마이그레이션
                    targets_response = events_src.list_targets_by_rule(
                        Rule=rule_name,
                        EventBusName=bus_name
                    )

                    if targets_response.get("Targets"):
                        new_targets = []
                        for target in targets_response["Targets"]:
                            # 원본 ARN 유효성 검증
                            src_target_arn = target["Arn"]
                            if not is_valid_arn(src_target_arn):
                                logger.error(f"  [SKIP] 유효하지 않은 타겟 ARN: {src_target_arn}")
                                continue

                            new_target = {
                                "Id": target["Id"],
                                "Arn": src_target_arn
                            }

                            # Lambda ARN 교체
                            if "lambda" in src_target_arn:
                                mapped_arn = LAMBDA_ARN_MAP.get(src_target_arn)
                                if mapped_arn:
                                    new_target["Arn"] = mapped_arn
                                    logger.info(f"  Lambda 타겟 매핑: {src_target_arn} -> {mapped_arn}")
                                else:
                                    # 계정 ID만 교체
                                    new_target["Arn"] = src_target_arn.replace(src_account, dst_account)
                                    logger.warning(f"  매핑 없음, 계정만 교체: {new_target['Arn']}")

                            # StepFunction ARN 교체
                            elif "states" in src_target_arn:
                                mapped_arn = SFN_ARN_MAP.get(src_target_arn)
                                if mapped_arn:
                                    new_target["Arn"] = mapped_arn
                                    logger.info(f"  StepFunction 타겟 매핑: {src_target_arn} -> {mapped_arn}")
                                else:
                                    # 계정 ID만 교체
                                    new_target["Arn"] = src_target_arn.replace(src_account, dst_account)
                                    logger.warning(f"  매핑 없음, 계정만 교체: {new_target['Arn']}")

                            # 기타 ARN (SQS, SNS 등)은 계정 교체
                            else:
                                new_target["Arn"] = src_target_arn.replace(src_account, dst_account)

                            # 변환된 ARN 유효성 검증
                            if not is_valid_arn(new_target["Arn"]):
                                logger.error(f"  [SKIP] 변환된 ARN이 유효하지 않음: {src_target_arn} -> {new_target['Arn']}")
                                continue

                            # 추가 설정 복사
                            if target.get("RoleArn"):
                                new_target["RoleArn"] = map_role(target["RoleArn"])

                            if target.get("Input"):
                                new_target["Input"] = target["Input"]

                            if target.get("InputPath"):
                                new_target["InputPath"] = target["InputPath"]

                            if target.get("RetryPolicy"):
                                new_target["RetryPolicy"] = target["RetryPolicy"]

                            if target.get("DeadLetterConfig"):
                                dlq_arn = target["DeadLetterConfig"]["Arn"]
                                new_target["DeadLetterConfig"] = {
                                    "Arn": dlq_arn.replace(src_account, dst_account)
                                }

                            new_targets.append(new_target)

                        # 타겟 등록
                        if new_targets:
                            events_dst.put_targets(
                                Rule=rule_name,
                                EventBusName=bus_name,
                                Targets=new_targets
                            )
                            logger.info(f"  ✔ 타겟 등록 완료 ({len(new_targets)}개)")

                    # 태그 복제
                    try:
                        src_rule_arn = rule["Arn"]
                        tags_response = events_src.list_tags_for_resource(ResourceARN=src_rule_arn)
                        if tags_response.get("Tags"):
                            # 대상 규칙 ARN 생성
                            dst_rule_arn = src_rule_arn.replace(src_account, dst_account)
                            events_dst.tag_resource(
                                ResourceARN=dst_rule_arn,
                                Tags=tags_response["Tags"]
                            )
                            logger.info(f"  ✔ 태그 복제 완료 ({len(tags_response['Tags'])}개)")
                    except ClientError as e:
                        logger.warning(f"  [WARN] 태그 복제 실패: {e}")

                except Exception as e:
                    logger.error(f"  ❌ 오류 발생: {rule_name} - {e}")
                    continue

    logger.info("\n📅 EventBridge 규칙 마이그레이션 완료!")


# ===================================================
# 실행
# ===================================================
def main():
    logger.info("\n" + "="*70)
    logger.info("🚀 AWS 리소스 마이그레이션 시작")
    logger.info("="*70)
    logger.info(f"소스 프로파일: {SRC_PROFILE}")
    logger.info(f"대상 프로파일: {DST_PROFILE}")
    logger.info(f"리전: {REGION}")
    logger.info(f"이름 접두사 필터: {NAME_PREFIX if NAME_PREFIX else '(전체)'}")
    logger.info("="*70)

    # 세션 생성
    src_sess = boto3.Session(profile_name=SRC_PROFILE, region_name=REGION)
    dst_sess = boto3.Session(profile_name=DST_PROFILE, region_name=REGION)

    # 계정 ID 추출
    src_sts = src_sess.client("sts")
    dst_sts = dst_sess.client("sts")
    src_account = src_sts.get_caller_identity()["Account"]
    dst_account = dst_sts.get_caller_identity()["Account"]

    logger.info(f"소스 계정: {src_account}")
    logger.info(f"대상 계정: {dst_account}")

    # 클라이언트 생성
    lambda_src = src_sess.client("lambda")
    lambda_dst = dst_sess.client("lambda")
    sfn_src = src_sess.client("stepfunctions")
    sfn_dst = dst_sess.client("stepfunctions")
    events_src = src_sess.client("events")
    events_dst = dst_sess.client("events")

    try:
        # 1) Layer 먼저 복제
        migrate_layers(lambda_src, lambda_dst)

        # 2) Lambda 복제
        migrate_lambdas(lambda_src, lambda_dst, src_account, dst_account)

        # 3) Step Functions 복제
        migrate_step_functions(sfn_src, sfn_dst, src_account, dst_account)

        # 4) EventBridge 규칙 복제
        migrate_eventbridge_rules(events_src, events_dst, src_account, dst_account)

        logger.info("\n" + "="*70)
        logger.info("✅ 전체 마이그레이션 완료!")
        logger.info("="*70)
        logger.info(f"Layer: {len(LAYER_MAP)}개")
        logger.info(f"Lambda: {len(LAMBDA_ARN_MAP)}개")
        logger.info(f"Step Functions: {len(SFN_ARN_MAP)}개")
        logger.info("="*70)

    except Exception as e:
        logger.error(f"\n❌ 마이그레이션 중 치명적 오류 발생: {e}")
        raise


if __name__ == "__main__":
    main()
