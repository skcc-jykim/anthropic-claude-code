#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import boto3
import logging
import time
from botocore.exceptions import ClientError
from typing import Optional, Dict, List

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

# Lambda ARN 매핑 (기존 Lambda 마이그레이션 결과 사용)
# 환경변수로 JSON 형태로 전달 가능
LAMBDA_ARN_MAP_JSON = os.getenv("LAMBDA_ARN_MAP", "{}")
LAMBDA_ARN_MAP: Dict[str, str] = {}

# 동적으로 채워질 매핑
API_MAP: Dict[str, str] = {}  # 소스 API ID -> 대상 API ID
STAGE_MAP: Dict[str, Dict[str, str]] = {}  # API ID -> {stage_name: stage_arn}

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
        return None
    return wrapper


def replace_lambda_arns_in_integration(integration: dict, src_account: str, dst_account: str) -> dict:
    """
    API Gateway Integration에서 Lambda ARN 교체
    """
    if not integration:
        return integration

    new_integration = integration.copy()

    # Integration URI에서 Lambda ARN 교체
    if 'uri' in new_integration and new_integration['uri']:
        uri = new_integration['uri']
        # Lambda 통합 URI 형식: arn:aws:apigateway:region:lambda:path/2015-03-31/functions/LAMBDA_ARN/invocations
        if 'lambda' in uri and src_account in uri:
            # Lambda ARN 추출
            for src_arn, dst_arn in LAMBDA_ARN_MAP.items():
                if src_arn in uri:
                    new_integration['uri'] = uri.replace(src_arn, dst_arn)
                    logger.info(f"    Replaced Lambda ARN in URI: {src_arn} -> {dst_arn}")
                    break
            else:
                # 매핑을 찾지 못하면 계정 ID만 교체
                new_integration['uri'] = uri.replace(src_account, dst_account)
                logger.warning(f"    No mapping found, replaced account ID in URI")

    # Credentials ARN 교체 (Lambda 호출 역할)
    if 'credentials' in new_integration and new_integration['credentials']:
        credentials = new_integration['credentials']
        if src_account in credentials:
            new_integration['credentials'] = credentials.replace(src_account, dst_account)
            logger.info(f"    Replaced credentials ARN")

    return new_integration


# ===================================================
# API Gateway 마이그레이션
# ===================================================

@retry_on_throttle
def migrate_rest_apis(apigw_src, apigw_dst, src_account: str, dst_account: str):
    """REST API 마이그레이션 (Export/Import 방식)"""

    logger.info("\n" + "="*50)
    logger.info("🌐 API Gateway REST API 마이그레이션 시작")
    logger.info("="*50)

    # REST API 목록 가져오기
    paginator = apigw_src.get_paginator("get_rest_apis")

    for page in paginator.paginate():
        for api in page.get("items", []):
            api_name = api["name"]
            src_api_id = api["id"]

            if NAME_PREFIX and not api_name.startswith(NAME_PREFIX):
                continue

            logger.info(f"\n{'='*50}")
            logger.info(f"🔄 API 마이그레이션 중: {api_name}")
            logger.info(f"{'='*50}")

            try:
                # API 상세 정보
                logger.info(f"  소스 API ID: {src_api_id}")
                logger.info(f"  API 타입: {api.get('endpointConfiguration', {}).get('types', ['EDGE'])}")

                # 1. API Export (OpenAPI/Swagger 형식)
                logger.info(f"  API 정의 내보내는 중...")

                # Stages 목록 가져오기
                stages = apigw_src.get_stages(restApiId=src_api_id).get("item", [])

                # 첫 번째 stage를 기준으로 export (또는 특정 stage 지정)
                export_stage = None
                if stages:
                    export_stage = stages[0]["stageName"]
                    logger.info(f"  Export 기준 Stage: {export_stage}")

                # API Export
                export_params = {
                    "restApiId": src_api_id,
                    "exportType": "oas30",  # OpenAPI 3.0 형식
                    "accepts": "application/json"
                }

                if export_stage:
                    export_params["stageName"] = export_stage

                export_response = apigw_src.get_export(**export_params)
                api_definition = json.loads(export_response["body"].read())

                # 2. Lambda ARN 교체 (API 정의에서)
                logger.info(f"  Lambda ARN 교체 중...")
                api_definition_str = json.dumps(api_definition)

                # Lambda ARN 매핑 적용
                for src_arn, dst_arn in LAMBDA_ARN_MAP.items():
                    if src_arn in api_definition_str:
                        api_definition_str = api_definition_str.replace(src_arn, dst_arn)
                        logger.info(f"    Replaced: {src_arn} -> {dst_arn}")

                # 계정 ID 교체 (매핑되지 않은 ARN들)
                api_definition_str = api_definition_str.replace(src_account, dst_account)
                api_definition = json.loads(api_definition_str)

                # 3. 대상 계정에 API 존재 여부 확인
                dst_api_id = None
                dst_apis = apigw_dst.get_rest_apis().get("items", [])

                for dst_api in dst_apis:
                    if dst_api["name"] == api_name:
                        dst_api_id = dst_api["id"]
                        logger.info(f"  기존 API 발견: {dst_api_id}")
                        break

                # 4. API Import (생성 또는 업데이트)
                import_params = {
                    "body": json.dumps(api_definition),
                    "failOnWarnings": False
                }

                if dst_api_id:
                    # 기존 API 업데이트 (PUT 모드)
                    logger.info(f"  기존 API 업데이트 중...")
                    import_params["restApiId"] = dst_api_id
                    import_params["mode"] = "overwrite"

                    response = apigw_dst.put_rest_api(**import_params)
                    dst_api_id = response["id"]
                    logger.info(f"  ✔ API 업데이트 완료: {dst_api_id}")
                else:
                    # 새 API 생성
                    logger.info(f"  새 API 생성 중...")
                    import_params["parameters"] = {
                        "endpointConfigurationTypes": ",".join(
                            api.get("endpointConfiguration", {}).get("types", ["EDGE"])
                        )
                    }

                    response = apigw_dst.import_rest_api(**import_params)
                    dst_api_id = response["id"]
                    logger.info(f"  ✔ API 생성 완료: {dst_api_id}")

                # API 매핑 저장
                API_MAP[src_api_id] = dst_api_id

                # 5. API 설정 업데이트 (Description 등)
                try:
                    update_params = {}

                    if api.get("description"):
                        update_params["patchOperations"] = [
                            {
                                "op": "replace",
                                "path": "/description",
                                "value": api["description"]
                            }
                        ]

                    if update_params:
                        apigw_dst.update_rest_api(
                            restApiId=dst_api_id,
                            **update_params
                        )
                        logger.info(f"  ✔ API 설정 업데이트 완료")

                except ClientError as e:
                    logger.warning(f"  [WARN] API 설정 업데이트 실패: {e}")

                # 6. 태그 복제
                try:
                    src_api_arn = f"arn:aws:apigateway:{REGION}::/restapis/{src_api_id}"
                    tags_response = apigw_src.get_tags(resourceArn=src_api_arn)

                    if tags_response.get("tags"):
                        dst_api_arn = f"arn:aws:apigateway:{REGION}::/restapis/{dst_api_id}"
                        apigw_dst.tag_resource(
                            resourceArn=dst_api_arn,
                            tags=tags_response["tags"]
                        )
                        logger.info(f"  ✔ 태그 복제 완료 ({len(tags_response['tags'])}개)")

                except ClientError as e:
                    logger.warning(f"  [WARN] 태그 복제 실패: {e}")

                # 7. Stages 마이그레이션
                logger.info(f"  Stages 마이그레이션 중...")
                migrate_stages(apigw_src, apigw_dst, src_api_id, dst_api_id, stages)

            except Exception as e:
                logger.error(f"  ❌ 오류 발생: {api_name} - {e}")
                import traceback
                logger.error(traceback.format_exc())
                continue

    logger.info(f"\n🌐 REST API 마이그레이션 완료! (총 {len(API_MAP)}개)")


@retry_on_throttle
def migrate_stages(apigw_src, apigw_dst, src_api_id: str, dst_api_id: str, src_stages: List[dict]):
    """API Gateway Stages 마이그레이션"""

    if not src_stages:
        logger.info(f"  마이그레이션할 Stage 없음")
        return

    for stage in src_stages:
        stage_name = stage["stageName"]

        logger.info(f"\n  ➡ Stage 처리 중: {stage_name}")

        try:
            # 대상에 Deployment 생성 (Stage에 필요)
            logger.info(f"    Deployment 생성 중...")

            deployment_response = apigw_dst.create_deployment(
                restApiId=dst_api_id,
                stageName=stage_name,
                description=stage.get("description", f"Migrated from {src_api_id}")
            )

            deployment_id = deployment_response["id"]
            logger.info(f"    ✔ Deployment 생성 완료: {deployment_id}")

            # Stage 설정 업데이트
            patch_operations = []

            # Description
            if stage.get("description"):
                patch_operations.append({
                    "op": "replace",
                    "path": "/description",
                    "value": stage["description"]
                })

            # Cache 설정
            if stage.get("cacheClusterEnabled"):
                patch_operations.append({
                    "op": "replace",
                    "path": "/cacheClusterEnabled",
                    "value": str(stage["cacheClusterEnabled"]).lower()
                })

                if stage.get("cacheClusterSize"):
                    patch_operations.append({
                        "op": "replace",
                        "path": "/cacheClusterSize",
                        "value": stage["cacheClusterSize"]
                    })

            # Throttling 설정
            if stage.get("throttle"):
                throttle = stage["throttle"]
                if throttle.get("rateLimit"):
                    patch_operations.append({
                        "op": "replace",
                        "path": "/throttle/rateLimit",
                        "value": str(throttle["rateLimit"])
                    })
                if throttle.get("burstLimit"):
                    patch_operations.append({
                        "op": "replace",
                        "path": "/throttle/burstLimit",
                        "value": str(throttle["burstLimit"])
                    })

            # Tracing (X-Ray) 설정
            if stage.get("tracingEnabled"):
                patch_operations.append({
                    "op": "replace",
                    "path": "/tracingEnabled",
                    "value": str(stage["tracingEnabled"]).lower()
                })

            # Stage Variables
            if stage.get("variables"):
                for key, value in stage["variables"].items():
                    patch_operations.append({
                        "op": "replace",
                        "path": f"/variables/{key}",
                        "value": value
                    })

            # Stage 업데이트
            if patch_operations:
                apigw_dst.update_stage(
                    restApiId=dst_api_id,
                    stageName=stage_name,
                    patchOperations=patch_operations
                )
                logger.info(f"    ✔ Stage 설정 업데이트 완료")

            # 태그 복제
            try:
                src_stage_arn = f"arn:aws:apigateway:{REGION}::/restapis/{src_api_id}/stages/{stage_name}"
                tags_response = apigw_src.get_tags(resourceArn=src_stage_arn)

                if tags_response.get("tags"):
                    dst_stage_arn = f"arn:aws:apigateway:{REGION}::/restapis/{dst_api_id}/stages/{stage_name}"
                    apigw_dst.tag_resource(
                        resourceArn=dst_stage_arn,
                        tags=tags_response["tags"]
                    )
                    logger.info(f"    ✔ Stage 태그 복제 완료 ({len(tags_response['tags'])}개)")

            except ClientError as e:
                logger.warning(f"    [WARN] Stage 태그 복제 실패: {e}")

        except Exception as e:
            logger.error(f"    ❌ Stage 처리 실패: {stage_name} - {e}")
            continue


@retry_on_throttle
def migrate_api_keys(apigw_src, apigw_dst):
    """API Keys 마이그레이션"""

    logger.info("\n" + "="*50)
    logger.info("🔑 API Keys 마이그레이션 시작")
    logger.info("="*50)

    api_key_map = {}  # 소스 키 ID -> 대상 키 ID

    paginator = apigw_src.get_paginator("get_api_keys")

    for page in paginator.paginate(includeValues=True):
        for key in page.get("items", []):
            key_name = key.get("name")

            if NAME_PREFIX and not key_name.startswith(NAME_PREFIX):
                continue

            logger.info(f"\n➡ API Key 마이그레이션 중: {key_name}")

            try:
                # 대상에 API Key 존재 여부 확인
                dst_keys = apigw_dst.get_api_keys().get("items", [])
                dst_key_id = None

                for dst_key in dst_keys:
                    if dst_key.get("name") == key_name:
                        dst_key_id = dst_key["id"]
                        logger.info(f"  기존 API Key 발견: {dst_key_id}")
                        break

                if not dst_key_id:
                    # 새 API Key 생성
                    logger.info(f"  새 API Key 생성 중...")

                    create_params = {
                        "name": key_name,
                        "enabled": key.get("enabled", True)
                    }

                    if key.get("description"):
                        create_params["description"] = key["description"]

                    # API Key 값 복제 (가능한 경우)
                    if key.get("value"):
                        create_params["value"] = key["value"]

                    response = apigw_dst.create_api_key(**create_params)
                    dst_key_id = response["id"]
                    logger.info(f"  ✔ API Key 생성 완료: {dst_key_id}")

                # 매핑 저장
                api_key_map[key["id"]] = dst_key_id

                # 태그 복제
                try:
                    src_key_arn = f"arn:aws:apigateway:{REGION}::/apikeys/{key['id']}"
                    tags_response = apigw_src.get_tags(resourceArn=src_key_arn)

                    if tags_response.get("tags"):
                        dst_key_arn = f"arn:aws:apigateway:{REGION}::/apikeys/{dst_key_id}"
                        apigw_dst.tag_resource(
                            resourceArn=dst_key_arn,
                            tags=tags_response["tags"]
                        )
                        logger.info(f"  ✔ API Key 태그 복제 완료 ({len(tags_response['tags'])}개)")

                except ClientError as e:
                    logger.warning(f"  [WARN] API Key 태그 복제 실패: {e}")

            except Exception as e:
                logger.error(f"  ❌ 오류 발생: {key_name} - {e}")
                continue

    logger.info(f"\n🔑 API Keys 마이그레이션 완료! (총 {len(api_key_map)}개)")
    return api_key_map


@retry_on_throttle
def migrate_usage_plans(apigw_src, apigw_dst, api_key_map: Dict[str, str]):
    """Usage Plans 마이그레이션"""

    logger.info("\n" + "="*50)
    logger.info("📊 Usage Plans 마이그레이션 시작")
    logger.info("="*50)

    paginator = apigw_src.get_paginator("get_usage_plans")

    for page in paginator.paginate():
        for plan in page.get("items", []):
            plan_name = plan.get("name")

            if NAME_PREFIX and not plan_name.startswith(NAME_PREFIX):
                continue

            logger.info(f"\n➡ Usage Plan 마이그레이션 중: {plan_name}")

            try:
                # 대상에 Usage Plan 존재 여부 확인
                dst_plans = apigw_dst.get_usage_plans().get("items", [])
                dst_plan_id = None

                for dst_plan in dst_plans:
                    if dst_plan.get("name") == plan_name:
                        dst_plan_id = dst_plan["id"]
                        logger.info(f"  기존 Usage Plan 발견: {dst_plan_id}")
                        break

                # Usage Plan 생성 파라미터
                plan_params = {
                    "name": plan_name
                }

                if plan.get("description"):
                    plan_params["description"] = plan["description"]

                # API Stages 매핑
                if plan.get("apiStages"):
                    mapped_stages = []
                    for stage_info in plan["apiStages"]:
                        src_api_id = stage_info.get("apiId")
                        stage_name = stage_info.get("stage")

                        # API 매핑 확인
                        dst_api_id = API_MAP.get(src_api_id)
                        if dst_api_id:
                            mapped_stages.append({
                                "apiId": dst_api_id,
                                "stage": stage_name
                            })
                            logger.info(f"  API Stage 매핑: {src_api_id}/{stage_name} -> {dst_api_id}/{stage_name}")
                        else:
                            logger.warning(f"  [WARN] API 매핑 없음: {src_api_id}")

                    if mapped_stages:
                        plan_params["apiStages"] = mapped_stages

                # Throttle 설정
                if plan.get("throttle"):
                    plan_params["throttle"] = plan["throttle"]

                # Quota 설정
                if plan.get("quota"):
                    plan_params["quota"] = plan["quota"]

                # Usage Plan 생성/업데이트
                if dst_plan_id:
                    logger.info(f"  기존 Usage Plan 업데이트 중...")
                    # 업데이트는 patch operations 사용
                    patch_ops = []

                    if plan.get("description"):
                        patch_ops.append({
                            "op": "replace",
                            "path": "/description",
                            "value": plan["description"]
                        })

                    if patch_ops:
                        apigw_dst.update_usage_plan(
                            usagePlanId=dst_plan_id,
                            patchOperations=patch_ops
                        )

                    logger.info(f"  ✔ Usage Plan 업데이트 완료: {dst_plan_id}")
                else:
                    logger.info(f"  새 Usage Plan 생성 중...")
                    response = apigw_dst.create_usage_plan(**plan_params)
                    dst_plan_id = response["id"]
                    logger.info(f"  ✔ Usage Plan 생성 완료: {dst_plan_id}")

                # API Keys 연결
                src_plan_keys = apigw_src.get_usage_plan_keys(usagePlanId=plan["id"]).get("items", [])

                for key_info in src_plan_keys:
                    src_key_id = key_info["id"]
                    dst_key_id = api_key_map.get(src_key_id)

                    if dst_key_id:
                        try:
                            apigw_dst.create_usage_plan_key(
                                usagePlanId=dst_plan_id,
                                keyId=dst_key_id,
                                keyType="API_KEY"
                            )
                            logger.info(f"  ✔ API Key 연결: {dst_key_id}")
                        except ClientError as e:
                            if e.response["Error"]["Code"] == "ConflictException":
                                logger.info(f"  API Key 이미 연결됨: {dst_key_id}")
                            else:
                                raise
                    else:
                        logger.warning(f"  [WARN] API Key 매핑 없음: {src_key_id}")

                # 태그 복제
                try:
                    src_plan_arn = f"arn:aws:apigateway:{REGION}::/usageplans/{plan['id']}"
                    tags_response = apigw_src.get_tags(resourceArn=src_plan_arn)

                    if tags_response.get("tags"):
                        dst_plan_arn = f"arn:aws:apigateway:{REGION}::/usageplans/{dst_plan_id}"
                        apigw_dst.tag_resource(
                            resourceArn=dst_plan_arn,
                            tags=tags_response["tags"]
                        )
                        logger.info(f"  ✔ Usage Plan 태그 복제 완료 ({len(tags_response['tags'])}개)")

                except ClientError as e:
                    logger.warning(f"  [WARN] Usage Plan 태그 복제 실패: {e}")

            except Exception as e:
                logger.error(f"  ❌ 오류 발생: {plan_name} - {e}")
                continue

    logger.info("\n📊 Usage Plans 마이그레이션 완료!")


# ===================================================
# 실행
# ===================================================
def main():
    logger.info("\n" + "="*70)
    logger.info("🌐 API Gateway 마이그레이션 시작")
    logger.info("="*70)
    logger.info(f"소스 프로파일: {SRC_PROFILE}")
    logger.info(f"대상 프로파일: {DST_PROFILE}")
    logger.info(f"리전: {REGION}")
    logger.info(f"이름 접두사 필터: {NAME_PREFIX if NAME_PREFIX else '(전체)'}")
    logger.info("="*70)

    # Lambda ARN 매핑 로드
    global LAMBDA_ARN_MAP
    try:
        if LAMBDA_ARN_MAP_JSON:
            LAMBDA_ARN_MAP = json.loads(LAMBDA_ARN_MAP_JSON)
            logger.info(f"Lambda ARN 매핑 로드: {len(LAMBDA_ARN_MAP)}개")
    except Exception as e:
        logger.warning(f"Lambda ARN 매핑 로드 실패: {e}")
        logger.warning("Lambda 통합이 있는 API의 경우 수동으로 ARN을 수정해야 할 수 있습니다.")

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
    apigw_src = src_sess.client("apigateway")
    apigw_dst = dst_sess.client("apigateway")

    try:
        # 1) REST APIs 마이그레이션
        migrate_rest_apis(apigw_src, apigw_dst, src_account, dst_account)

        # 2) API Keys 마이그레이션
        api_key_map = migrate_api_keys(apigw_src, apigw_dst)

        # 3) Usage Plans 마이그레이션
        migrate_usage_plans(apigw_src, apigw_dst, api_key_map)

        logger.info("\n" + "="*70)
        logger.info("✅ API Gateway 마이그레이션 완료!")
        logger.info("="*70)
        logger.info(f"🌐 REST APIs: {len(API_MAP)}개")
        logger.info(f"🔑 API Keys: {len(api_key_map)}개")
        logger.info(f"📊 Usage Plans: 복제 완료")
        logger.info("="*70)

        # Lambda 권한 추가 안내
        if API_MAP:
            logger.info("\n⚠️  추가 작업 필요:")
            logger.info("API Gateway가 Lambda를 호출하려면 Lambda에 권한을 추가해야 합니다:")
            logger.info("aws lambda add-permission \\")
            logger.info("  --function-name <LAMBDA_NAME> \\")
            logger.info("  --statement-id apigateway-invoke \\")
            logger.info("  --action lambda:InvokeFunction \\")
            logger.info("  --principal apigateway.amazonaws.com \\")
            logger.info("  --source-arn 'arn:aws:execute-api:REGION:ACCOUNT:API_ID/*'")

    except Exception as e:
        logger.error(f"\n❌ 마이그레이션 중 치명적 오류 발생: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
