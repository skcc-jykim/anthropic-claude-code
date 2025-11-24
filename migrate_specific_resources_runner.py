#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
특정 리소스 마이그레이션 실행 스크립트

target_*.txt 파일에 정의된 리소스만 마이그레이션합니다.
"""

import os
import sys
import json
import logging
import boto3
from pathlib import Path
from typing import Optional, Dict, Set
from botocore.exceptions import ClientError

# 기존 마이그레이션 스크립트에서 필요한 함수들 import
# (migrate_aws_resources.py와 동일한 디렉토리에 있어야 함)
try:
    from migrate_aws_resources import (
        retry_on_throttle,
        download_code,
        map_vpc_config,
        map_role,
        extract_account_from_arn,
        is_valid_arn,
        replace_lambda_arns_in_definition,
        create_eventbridge_execution_roles,
        migrate_ecr_image,
        # 글로벌 변수들
        REGION, SRC_PROFILE, DST_PROFILE,
        SUBNET_MAP, SG_MAP, ROLE_MAP,
        LAYER_MAP, LAMBDA_ARN_MAP, SFN_ARN_MAP, SCHEDULE_GROUP_ARN_MAP, ECR_IMAGE_MAP,
        DEFAULT_DEST_LAMBDA_ROLE, DEFAULT_DEST_SFN_ROLE,
        EVENTBRIDGE_RULES_ROLE_ARN, EVENTBRIDGE_SCHEDULER_ROLE_ARN,
        SKIP_MISSING_LAYERS, FAIL_ON_MISSING_LAYERS,
        MAX_RETRIES, RETRY_DELAY
    )
except ImportError as e:
    print(f"❌ migrate_aws_resources.py를 찾을 수 없습니다: {e}")
    print("   이 스크립트는 migrate_aws_resources.py와 같은 디렉토리에 있어야 합니다.")
    sys.exit(1)

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
SCRIPT_DIR = Path(__file__).parent
TARGET_LAMBDAS_FILE = SCRIPT_DIR / "target_lambdas.txt"
TARGET_STEPFUNCTIONS_FILE = SCRIPT_DIR / "target_stepfunctions.txt"
TARGET_SCHEDULES_FILE = SCRIPT_DIR / "target_schedules.txt"


def load_resource_list(file_path: Path) -> Set[str]:
    """리소스 목록 파일 로드"""
    resources = set()

    if not file_path.exists():
        logger.warning(f"⚠️  리소스 목록 파일을 찾을 수 없습니다: {file_path}")
        return resources

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # 빈 줄이나 주석(#으로 시작) 무시
                if line and not line.startswith('#'):
                    resources.add(line)

        logger.info(f"📋 리소스 목록 로드: {file_path.name} ({len(resources)}개)")
        return resources

    except Exception as e:
        logger.error(f"❌ 리소스 목록 파일 읽기 실패: {e}")
        return set()


# ===================================================
# Layer 마이그레이션 (필요한 Layer만)
# ===================================================
@retry_on_throttle
def migrate_required_layers(lambda_src, lambda_dst, required_layer_arns: Set[str]):
    """필요한 Layer만 선택적으로 마이그레이션"""
    import tempfile
    import time
    import requests

    if not required_layer_arns:
        logger.info("마이그레이션할 Layer가 없습니다.")
        return

    logger.info("\n" + "="*50)
    logger.info(f"🔧 필요한 Layer 마이그레이션 시작 ({len(required_layer_arns)}개)")
    logger.info("="*50)

    layer_success_count = 0
    layer_fail_count = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        for src_arn in required_layer_arns:
            # 이미 매핑된 경우 skip
            if src_arn in LAYER_MAP:
                logger.info(f"  [SKIP] 이미 매핑됨: {src_arn}")
                continue

            try:
                # ARN 파싱: arn:aws:lambda:region:account:layer:layer-name:version
                parts = src_arn.split(":")
                if len(parts) < 8:
                    logger.error(f"  ❌ 유효하지 않은 Layer ARN: {src_arn}")
                    layer_fail_count += 1
                    continue

                layer_name = parts[6]
                version_number = int(parts[7])

                logger.info(f"\n➡ Layer 처리 중: {layer_name}:{version_number}")

                # Layer 상세 정보 가져오기
                layer_detail = lambda_src.get_layer_version(
                    LayerName=layer_name,
                    VersionNumber=version_number
                )

                # Layer ZIP 다운로드
                code_url = layer_detail["Content"]["Location"]
                zip_path = os.path.join(tmpdir, f"{layer_name}-{version_number}.zip")

                logger.info(f"  다운로드 중...")
                r = requests.get(code_url, stream=True, timeout=300)
                r.raise_for_status()
                with open(zip_path, "wb") as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)

                # 대상 계정에 Layer 버전 존재하는지 확인
                dst_arn = None
                try:
                    dst_versions = lambda_dst.list_layer_versions(LayerName=layer_name).get("LayerVersions", [])
                    for dv in dst_versions:
                        if dv["Version"] == version_number:
                            dst_arn = dv["LayerVersionArn"]
                            logger.info(f"  대상에 이미 존재: {dst_arn}")
                            break
                except ClientError:
                    pass

                # 대상 계정에 없으면 생성
                if not dst_arn:
                    logger.info(f"  생성 중...")
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
                layer_success_count += 1

            except Exception as e:
                logger.error(f"  ❌ Layer 마이그레이션 실패: {e}")
                layer_fail_count += 1

    logger.info(f"\n✅ Layer 마이그레이션 완료: 성공 {layer_success_count}개, 실패 {layer_fail_count}개")


# ===================================================
# Lambda 마이그레이션 (선택적)
# ===================================================
@retry_on_throttle
def migrate_specific_lambdas(
    lambda_src,
    lambda_dst,
    src_account: str,
    dst_account: str,
    target_lambdas: Set[str],
    src_ecr_client=None,
    dst_ecr_client=None,
    region: str = REGION
):
    """특정 Lambda 함수만 마이그레이션"""
    import tempfile
    import time

    logger.info("\n" + "="*50)
    logger.info(f"🚀 Lambda 함수 마이그레이션 시작 ({len(target_lambdas)}개)")
    logger.info("="*50)

    # 먼저 모든 Lambda 함수 목록 가져오기
    all_functions = {}
    paginator = lambda_src.get_paginator("list_functions")
    for page in paginator.paginate():
        for fn in page["Functions"]:
            all_functions[fn["FunctionName"]] = fn

    # 타겟 Lambda 함수만 필터링
    migrated_count = 0
    skipped_count = 0
    not_found = []

    # 필요한 Layer ARN 수집
    required_layer_arns = set()

    for name in sorted(target_lambdas):
        if name not in all_functions:
            logger.warning(f"⚠️  Lambda 함수를 찾을 수 없음: {name}")
            not_found.append(name)
            skipped_count += 1
            continue

        fn = all_functions[name]

        logger.info(f"\n{'='*50}")
        logger.info(f"🔄 마이그레이션 중: {name}")
        logger.info(f"{'='*50}")

        try:
            cfg = lambda_src.get_function_configuration(FunctionName=name)
            code_info = lambda_src.get_function(FunctionName=name)["Code"]
            package_type = cfg.get("PackageType", "Zip")

            # Layer ARN 수집
            if cfg.get("Layers"):
                for layer in cfg["Layers"]:
                    required_layer_arns.add(layer["Arn"])

            # 컨테이너 이미지 Lambda 처리
            if package_type == "Image":
                logger.info(f"  📦 컨테이너 이미지 Lambda")

                if not src_ecr_client or not dst_ecr_client:
                    logger.warning(f"  [SKIP] ECR 클라이언트가 제공되지 않음")
                    skipped_count += 1
                    continue

                src_image_uri = code_info.get("ImageUri")
                if not src_image_uri:
                    logger.error(f"  ❌ 이미지 URI를 찾을 수 없음")
                    skipped_count += 1
                    continue

                logger.info(f"  원본 이미지: {src_image_uri}")

                try:
                    dst_image_uri = migrate_ecr_image(
                        src_image_uri,
                        src_ecr_client,
                        dst_ecr_client,
                        src_account,
                        dst_account,
                        region
                    )

                    common_params = {
                        "FunctionName": name,
                        "Role": map_role(cfg["Role"]),
                        "Timeout": cfg["Timeout"],
                        "MemorySize": cfg["MemorySize"],
                        "Description": cfg.get("Description", ""),
                        "PackageType": "Image"
                    }

                    if cfg.get("ImageConfigResponse"):
                        image_config = cfg["ImageConfigResponse"].get("ImageConfig")
                        if image_config:
                            common_params["ImageConfig"] = {}
                            if image_config.get("EntryPoint"):
                                common_params["ImageConfig"]["EntryPoint"] = image_config["EntryPoint"]
                            if image_config.get("Command"):
                                common_params["ImageConfig"]["Command"] = image_config["Command"]
                            if image_config.get("WorkingDirectory"):
                                common_params["ImageConfig"]["WorkingDirectory"] = image_config["WorkingDirectory"]

                except Exception as e:
                    logger.error(f"  ❌ ECR 이미지 마이그레이션 실패: {e}")
                    skipped_count += 1
                    continue

            # ZIP 기반 Lambda 처리
            else:
                zip_url = code_info["Location"]
                with tempfile.TemporaryDirectory() as tmpdir:
                    zip_path = os.path.join(tmpdir, f"{name}.zip")
                    download_code(zip_url, zip_path)
                    with open(zip_path, "rb") as f:
                        zip_bytes = f.read()

                common_params = {
                    "FunctionName": name,
                    "Role": map_role(cfg["Role"]),
                    "Runtime": cfg["Runtime"],
                    "Handler": cfg["Handler"],
                    "Timeout": cfg["Timeout"],
                    "MemorySize": cfg["MemorySize"],
                    "Description": cfg.get("Description", "")
                }

            # Environment
            if cfg.get("Environment") and cfg["Environment"].get("Variables"):
                common_params["Environment"] = cfg["Environment"]

            # Layers (ZIP 기반만)
            if package_type == "Zip" and cfg.get("Layers"):
                mapped = []
                for layer in cfg["Layers"]:
                    src_arn = layer["Arn"]
                    dst_arn = LAYER_MAP.get(src_arn)
                    if dst_arn:
                        mapped.append(dst_arn)
                    elif not SKIP_MISSING_LAYERS:
                        logger.warning(f"  ⚠️  Layer 매핑 없음: {src_arn}")
                        mapped.append(src_arn)
                if mapped:
                    common_params["Layers"] = mapped

            # VPC 설정
            vpc_cfg = map_vpc_config(cfg.get("VpcConfig"))
            if vpc_cfg and vpc_cfg.get("SubnetIds"):
                common_params["VpcConfig"] = vpc_cfg

            # Dead Letter Queue
            if cfg.get("DeadLetterConfig") and cfg["DeadLetterConfig"].get("TargetArn"):
                dlq_arn = cfg["DeadLetterConfig"]["TargetArn"]
                common_params["DeadLetterConfig"] = {
                    "TargetArn": dlq_arn.replace(src_account, dst_account)
                }

            # Tracing
            if cfg.get("TracingConfig") and cfg["TracingConfig"].get("Mode"):
                common_params["TracingConfig"] = cfg["TracingConfig"]

            # KMS Key
            if cfg.get("KMSKeyArn"):
                common_params["KMSKeyArn"] = cfg["KMSKeyArn"].replace(src_account, dst_account)

            # EphemeralStorage
            if cfg.get("EphemeralStorage"):
                common_params["EphemeralStorage"] = cfg["EphemeralStorage"]

            # FileSystemConfigs
            if cfg.get("FileSystemConfigs"):
                fs_configs = []
                for fs_config in cfg["FileSystemConfigs"]:
                    new_config = fs_config.copy()
                    if "Arn" in new_config:
                        new_config["Arn"] = new_config["Arn"].replace(src_account, dst_account)
                    fs_configs.append(new_config)
                common_params["FileSystemConfigs"] = fs_configs

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
                lambda_dst.update_function_configuration(**common_params)
                time.sleep(2)

                if package_type == "Image":
                    lambda_dst.update_function_code(FunctionName=name, ImageUri=dst_image_uri)
                else:
                    lambda_dst.update_function_code(FunctionName=name, ZipFile=zip_bytes)
                logger.info(f"  ✔ 업데이트 완료: {name}")
            else:
                logger.info(f"  새 함수 생성 중...")
                create_params = common_params.copy()
                create_params["Architectures"] = cfg.get("Architectures", ["x86_64"])

                if package_type == "Image":
                    create_params["Code"] = {"ImageUri": dst_image_uri}
                else:
                    create_params["Code"] = {"ZipFile": zip_bytes}
                    create_params["PackageType"] = "Zip"

                lambda_dst.create_function(**create_params)
                logger.info(f"  ✔ 생성 완료: {name}")

            # ARN 매핑 저장
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

            # 예약 동시성
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

            migrated_count += 1

        except Exception as e:
            logger.error(f"  ❌ 오류 발생: {name} - {e}")
            skipped_count += 1
            continue

    # 요약
    logger.info(f"\n{'='*50}")
    logger.info(f"🚀 Lambda 마이그레이션 완료!")
    logger.info(f"{'='*50}")
    logger.info(f"  ✅ 성공: {migrated_count}개")
    logger.info(f"  ⏭️  스킵: {skipped_count}개")
    logger.info(f"  ❓ 미발견: {len(not_found)}개")
    if not_found:
        logger.info(f"     - {', '.join(not_found)}")
    logger.info(f"{'='*50}\n")

    return required_layer_arns


# ===================================================
# Step Functions 마이그레이션 (선택적)
# ===================================================
@retry_on_throttle
def migrate_specific_stepfunctions(sfn_src, sfn_dst, src_account: str, dst_account: str, target_stepfunctions: Set[str]):
    """특정 Step Functions만 마이그레이션"""

    logger.info("\n" + "="*50)
    logger.info(f"⚙️  Step Functions 마이그레이션 시작 ({len(target_stepfunctions)}개)")
    logger.info("="*50)

    # 모든 상태 머신 목록 가져오기
    all_state_machines = {}
    paginator = sfn_src.get_paginator("list_state_machines")
    for page in paginator.paginate():
        for sm in page.get("stateMachines", []):
            all_state_machines[sm["name"]] = sm

    migrated_count = 0
    skipped_count = 0
    not_found = []

    for sm_name in sorted(target_stepfunctions):
        if sm_name not in all_state_machines:
            logger.warning(f"⚠️  Step Function을 찾을 수 없음: {sm_name}")
            not_found.append(sm_name)
            skipped_count += 1
            continue

        sm = all_state_machines[sm_name]
        src_arn = sm["stateMachineArn"]

        logger.info(f"\n{'='*50}")
        logger.info(f"🔄 상태 머신 마이그레이션 중: {sm_name}")
        logger.info(f"{'='*50}")

        try:
            # 상태 머신 상세 정보
            sm_detail = sfn_src.describe_state_machine(stateMachineArn=src_arn)

            # 정의에서 ARN 교체
            definition = json.loads(sm_detail["definition"])
            updated_definition = replace_lambda_arns_in_definition(definition, src_account, dst_account)

            params = {
                "name": sm_name,
                "definition": json.dumps(updated_definition, ensure_ascii=False),
                "roleArn": map_role(sm_detail["roleArn"], "sfn"),
                "type": sm_detail.get("type", "STANDARD")
            }

            # 생성/업데이트
            try:
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
                        roleArn=params["roleArn"]
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
                        sfn_dst.tag_resource(resourceArn=dst_arn, tags=tags_response["tags"])
                        logger.info(f"  ✔ 태그 복제 완료 ({len(tags_response['tags'])}개)")
                except ClientError as e:
                    logger.warning(f"  [WARN] 태그 복제 실패: {e}")

                migrated_count += 1

            except ClientError as e:
                logger.error(f"  ❌ 생성/업데이트 실패: {e}")
                skipped_count += 1
                continue

        except Exception as e:
            logger.error(f"  ❌ 오류 발생: {sm_name} - {e}")
            skipped_count += 1
            continue

    # 요약
    logger.info(f"\n{'='*50}")
    logger.info(f"⚙️  Step Functions 마이그레이션 완료!")
    logger.info(f"{'='*50}")
    logger.info(f"  ✅ 성공: {migrated_count}개")
    logger.info(f"  ⏭️  스킵: {skipped_count}개")
    logger.info(f"  ❓ 미발견: {len(not_found)}개")
    if not_found:
        logger.info(f"     - {', '.join(not_found)}")
    logger.info(f"{'='*50}\n")


# ===================================================
# EventBridge Scheduler 마이그레이션 (선택적)
# ===================================================
@retry_on_throttle
def migrate_specific_schedules(scheduler_src, scheduler_dst, src_account: str, dst_account: str, target_schedules: Set[str]):
    """특정 EventBridge Schedules만 마이그레이션"""

    logger.info("\n" + "="*50)
    logger.info(f"⏰ EventBridge Schedules 마이그레이션 시작 ({len(target_schedules)}개)")
    logger.info("="*50)

    # 스케줄을 그룹별로 분류
    schedules_by_group = {}
    for schedule_path in target_schedules:
        if '/' in schedule_path:
            group, name = schedule_path.split('/', 1)
        else:
            group = 'default'
            name = schedule_path

        if group not in schedules_by_group:
            schedules_by_group[group] = set()
        schedules_by_group[group].add(name)

    # 필요한 그룹 생성
    for group_name in schedules_by_group.keys():
        if group_name == 'default':
            continue

        try:
            try:
                scheduler_dst.get_schedule_group(Name=group_name)
                logger.info(f"  ✔ 그룹 존재: {group_name}")
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceNotFoundException":
                    logger.info(f"  그룹 생성 중: {group_name}")
                    scheduler_dst.create_schedule_group(Name=group_name)
                    logger.info(f"  ✔ 그룹 생성 완료: {group_name}")
                else:
                    raise
        except Exception as e:
            logger.error(f"  ❌ 그룹 생성 실패: {group_name} - {e}")

    # 각 그룹의 일정 마이그레이션
    migrated_count = 0
    skipped_count = 0
    not_found = []

    for group_name, schedule_names in sorted(schedules_by_group.items()):
        logger.info(f"\n📁 그룹: {group_name} ({len(schedule_names)}개)")

        # 해당 그룹의 모든 일정 가져오기
        all_schedules = {}
        try:
            paginator = scheduler_src.get_paginator("list_schedules")
            for page in paginator.paginate(GroupName=group_name):
                for schedule in page.get("Schedules", []):
                    all_schedules[schedule["Name"]] = schedule
        except Exception as e:
            logger.error(f"  ❌ 그룹 {group_name}의 일정 목록 가져오기 실패: {e}")
            continue

        for schedule_name in sorted(schedule_names):
            if schedule_name not in all_schedules:
                logger.warning(f"  ⚠️  일정을 찾을 수 없음: {schedule_name}")
                not_found.append(f"{group_name}/{schedule_name}")
                skipped_count += 1
                continue

            logger.info(f"\n  🔄 일정 마이그레이션 중: {schedule_name}")

            try:
                # 일정 상세 정보
                schedule_detail = scheduler_src.get_schedule(
                    Name=schedule_name,
                    GroupName=group_name
                )

                params = {
                    "Name": schedule_name,
                    "GroupName": group_name,
                    "ScheduleExpression": schedule_detail["ScheduleExpression"],
                    "FlexibleTimeWindow": schedule_detail["FlexibleTimeWindow"],
                    "Target": schedule_detail["Target"]
                }

                logger.info(f"     스케줄: {schedule_detail['ScheduleExpression']}")

                if schedule_detail.get("Description"):
                    params["Description"] = schedule_detail["Description"]
                if schedule_detail.get("State"):
                    params["State"] = schedule_detail["State"]
                if schedule_detail.get("StartDate"):
                    params["StartDate"] = schedule_detail["StartDate"]
                if schedule_detail.get("EndDate"):
                    params["EndDate"] = schedule_detail["EndDate"]
                if schedule_detail.get("ScheduleExpressionTimezone"):
                    params["ScheduleExpressionTimezone"] = schedule_detail["ScheduleExpressionTimezone"]
                if schedule_detail.get("KmsKeyArn"):
                    params["KmsKeyArn"] = schedule_detail["KmsKeyArn"].replace(src_account, dst_account)

                # Target ARN 매핑
                target = params["Target"]
                target_arn = target["Arn"]

                if "lambda" in target_arn:
                    mapped_arn = LAMBDA_ARN_MAP.get(target_arn)
                    if mapped_arn:
                        target["Arn"] = mapped_arn
                        logger.info(f"     Lambda 타겟 매핑: {target_arn} -> {mapped_arn}")
                    else:
                        target["Arn"] = target_arn.replace(src_account, dst_account)
                        logger.warning(f"     매핑 없음, 계정만 교체: {target['Arn']}")
                elif "states" in target_arn:
                    mapped_arn = SFN_ARN_MAP.get(target_arn)
                    if mapped_arn:
                        target["Arn"] = mapped_arn
                        logger.info(f"     StepFunction 타겟 매핑: {target_arn} -> {mapped_arn}")
                    else:
                        target["Arn"] = target_arn.replace(src_account, dst_account)
                        logger.warning(f"     매핑 없음, 계정만 교체: {target['Arn']}")
                else:
                    target["Arn"] = target_arn.replace(src_account, dst_account)

                # Role ARN
                target["RoleArn"] = EVENTBRIDGE_SCHEDULER_ROLE_ARN
                logger.info(f"     Role 설정: {EVENTBRIDGE_SCHEDULER_ROLE_ARN}")

                # DeadLetterConfig
                if target.get("DeadLetterConfig"):
                    dlq_arn = target["DeadLetterConfig"]["Arn"]
                    target["DeadLetterConfig"]["Arn"] = dlq_arn.replace(src_account, dst_account)

                # 생성/업데이트
                schedule_exists = False
                try:
                    scheduler_dst.get_schedule(Name=schedule_name, GroupName=group_name)
                    schedule_exists = True
                except ClientError as e:
                    if e.response["Error"]["Code"] != "ResourceNotFoundException":
                        raise

                if schedule_exists:
                    logger.info(f"     기존 일정 업데이트 중...")
                    scheduler_dst.update_schedule(**params)
                    logger.info(f"     ✔ 업데이트 완료: {schedule_name}")
                else:
                    logger.info(f"     새 일정 생성 중...")
                    scheduler_dst.create_schedule(**params)
                    logger.info(f"     ✔ 생성 완료: {schedule_name}")

                migrated_count += 1

                # 태그 복제
                try:
                    src_schedule_arn = schedule_detail["Arn"]
                    tags_response = scheduler_src.list_tags_for_resource(ResourceArn=src_schedule_arn)
                    if tags_response.get("Tags"):
                        dst_schedule = scheduler_dst.get_schedule(Name=schedule_name, GroupName=group_name)
                        dst_schedule_arn = dst_schedule["Arn"]
                        scheduler_dst.tag_resource(ResourceArn=dst_schedule_arn, Tags=tags_response["Tags"])
                        logger.info(f"     ✔ 태그 복제 완료 ({len(tags_response['Tags'])}개)")
                except ClientError as e:
                    logger.warning(f"     [WARN] 태그 복제 실패: {e}")

            except Exception as e:
                logger.error(f"     ❌ 오류 발생: {schedule_name} - {e}")
                skipped_count += 1
                continue

    # 요약
    logger.info(f"\n{'='*50}")
    logger.info(f"⏰ EventBridge Schedules 마이그레이션 완료!")
    logger.info(f"{'='*50}")
    logger.info(f"  ✅ 성공: {migrated_count}개")
    logger.info(f"  ⏭️  스킵: {skipped_count}개")
    logger.info(f"  ❓ 미발견: {len(not_found)}개")
    if not_found:
        logger.info(f"     - {', '.join(not_found[:10])}")
        if len(not_found) > 10:
            logger.info(f"     ... 외 {len(not_found) - 10}개")
    logger.info(f"{'='*50}\n")


# ===================================================
# 메인 실행
# ===================================================
def main():
    logger.info("\n" + "="*70)
    logger.info("🎯 특정 리소스 마이그레이션 시작")
    logger.info("="*70)
    logger.info(f"소스 프로파일: {SRC_PROFILE}")
    logger.info(f"대상 프로파일: {DST_PROFILE}")
    logger.info(f"리전: {REGION}")
    logger.info("="*70)

    # 1. 리소스 목록 로드
    logger.info("\n📂 리소스 목록 로드 중...")
    target_lambdas = load_resource_list(TARGET_LAMBDAS_FILE)
    target_stepfunctions = load_resource_list(TARGET_STEPFUNCTIONS_FILE)
    target_schedules = load_resource_list(TARGET_SCHEDULES_FILE)

    if not target_lambdas and not target_stepfunctions and not target_schedules:
        logger.error("❌ 마이그레이션할 리소스가 없습니다!")
        return 1

    logger.info(f"\n  🚀 Lambda: {len(target_lambdas)}개")
    logger.info(f"  ⚙️  Step Functions: {len(target_stepfunctions)}개")
    logger.info(f"  ⏰ Schedules: {len(target_schedules)}개")
    logger.info(f"  📦 총 리소스: {len(target_lambdas) + len(target_stepfunctions) + len(target_schedules)}개")

    # 2. AWS 세션 생성
    src_sess = boto3.Session(profile_name=SRC_PROFILE, region_name=REGION)
    dst_sess = boto3.Session(profile_name=DST_PROFILE, region_name=REGION)

    # 계정 ID
    src_sts = src_sess.client("sts")
    dst_sts = dst_sess.client("sts")
    src_account = src_sts.get_caller_identity()["Account"]
    dst_account = dst_sts.get_caller_identity()["Account"]

    logger.info(f"\n소스 계정: {src_account}")
    logger.info(f"대상 계정: {dst_account}")

    # 클라이언트 생성
    lambda_src = src_sess.client("lambda")
    lambda_dst = dst_sess.client("lambda")
    sfn_src = src_sess.client("stepfunctions")
    sfn_dst = dst_sess.client("stepfunctions")
    scheduler_src = src_sess.client("scheduler")
    scheduler_dst = dst_sess.client("scheduler")
    iam_dst = dst_sess.client("iam")
    ecr_src = src_sess.client("ecr")
    ecr_dst = dst_sess.client("ecr")

    try:
        # 3. EventBridge 실행 Role 생성
        create_eventbridge_execution_roles(iam_dst, dst_account)

        # 4. Lambda 마이그레이션 (Layer ARN 수집)
        required_layer_arns = set()
        if target_lambdas:
            required_layer_arns = migrate_specific_lambdas(
                lambda_src,
                lambda_dst,
                src_account,
                dst_account,
                target_lambdas,
                src_ecr_client=ecr_src,
                dst_ecr_client=ecr_dst,
                region=REGION
            )

        # 5. Layer 마이그레이션
        if required_layer_arns:
            migrate_required_layers(lambda_src, lambda_dst, required_layer_arns)

        # 6. Step Functions 마이그레이션
        if target_stepfunctions:
            migrate_specific_stepfunctions(sfn_src, sfn_dst, src_account, dst_account, target_stepfunctions)

        # 7. EventBridge Schedules 마이그레이션
        if target_schedules:
            migrate_specific_schedules(scheduler_src, scheduler_dst, src_account, dst_account, target_schedules)

        # 8. 완료 요약
        logger.info("\n" + "="*70)
        logger.info("✅ 전체 마이그레이션 완료!")
        logger.info("="*70)
        logger.info(f"🔧 Layer: {len(LAYER_MAP)}개")
        logger.info(f"📦 ECR 이미지: {len(ECR_IMAGE_MAP)}개")
        logger.info(f"🚀 Lambda: {len(LAMBDA_ARN_MAP)}개")
        logger.info(f"⚙️  Step Functions: {len(SFN_ARN_MAP)}개")
        logger.info(f"⏰ EventBridge Schedules: 복제 완료")
        logger.info("="*70)

        return 0

    except Exception as e:
        logger.error(f"\n❌ 마이그레이션 중 치명적 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
