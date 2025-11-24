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

# KMS 키 매핑 (선택적)
# 소스 계정의 KMS 키 ARN -> 대상 계정의 KMS 키 ARN
KMS_KEY_MAP_JSON = os.getenv("KMS_KEY_MAP", "{}")
KMS_KEY_MAP: Dict[str, str] = {}

# 재시도 설정
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

# 통계
STATS = {
    "total": 0,
    "created": 0,
    "updated": 0,
    "failed": 0,
    "skipped": 0
}


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


def map_kms_key(src_kms_arn: str, dst_account: str) -> Optional[str]:
    """
    KMS 키 ARN 매핑
    - KMS_KEY_MAP에 명시적 매핑이 있으면 사용
    - 없으면 None 반환 (AWS 기본 키 사용)
    """
    if not src_kms_arn:
        return None

    # 명시적 매핑 확인
    if src_kms_arn in KMS_KEY_MAP:
        return KMS_KEY_MAP[src_kms_arn]

    # AWS 관리형 키인 경우 (alias/aws/secretsmanager)
    if "alias/aws/secretsmanager" in src_kms_arn:
        # 대상 계정의 AWS 관리형 키로 자동 매핑
        return f"arn:aws:kms:{REGION}:{dst_account}:alias/aws/secretsmanager"

    # 매핑이 없으면 None (기본 키 사용)
    logger.warning(f"  [WARN] KMS 키 매핑 없음: {src_kms_arn} -> 기본 키 사용")
    return None


# ===================================================
# Secrets Manager 마이그레이션
# ===================================================

@retry_on_throttle
def migrate_secrets(sm_src, sm_dst, src_account: str, dst_account: str):
    """AWS Secrets Manager 시크릿 마이그레이션"""

    logger.info("\n" + "="*70)
    logger.info("🔐 AWS Secrets Manager 마이그레이션 시작")
    logger.info("="*70)

    # 시크릿 목록 가져오기
    paginator = sm_src.get_paginator("list_secrets")

    for page in paginator.paginate():
        for secret in page.get("SecretList", []):
            secret_name = secret["Name"]
            STATS["total"] += 1

            # 이름 필터 확인
            if NAME_PREFIX and not secret_name.startswith(NAME_PREFIX):
                STATS["skipped"] += 1
                continue

            # 삭제 예정인 시크릿 스킵
            if secret.get("DeletedDate"):
                logger.info(f"\n⏭  시크릿 스킵 (삭제 예정): {secret_name}")
                STATS["skipped"] += 1
                continue

            logger.info(f"\n{'='*70}")
            logger.info(f"🔄 시크릿 마이그레이션 중: {secret_name}")
            logger.info(f"{'='*70}")

            try:
                # 1. 소스 시크릿 상세 정보 가져오기
                logger.info(f"  시크릿 정보 조회 중...")
                src_secret_detail = sm_src.describe_secret(SecretId=secret_name)

                # 2. 시크릿 값 가져오기
                logger.info(f"  시크릿 값 조회 중...")
                try:
                    secret_value_response = sm_src.get_secret_value(SecretId=secret_name)
                    secret_string = secret_value_response.get("SecretString")
                    secret_binary = secret_value_response.get("SecretBinary")
                    version_id = secret_value_response.get("VersionId")
                    version_stages = secret_value_response.get("VersionStages", [])

                    logger.info(f"  시크릿 버전: {version_id}")
                    logger.info(f"  버전 스테이지: {', '.join(version_stages)}")

                except ClientError as e:
                    if e.response["Error"]["Code"] == "ResourceNotFoundException":
                        logger.warning(f"  [WARN] 시크릿 값이 없음 (비어있음)")
                        secret_string = None
                        secret_binary = None
                    else:
                        raise

                # 3. 대상 계정에 시크릿 존재 여부 확인
                dst_secret_exists = False
                try:
                    sm_dst.describe_secret(SecretId=secret_name)
                    dst_secret_exists = True
                    logger.info(f"  기존 시크릿 발견: {secret_name}")
                except ClientError as e:
                    if e.response["Error"]["Code"] == "ResourceNotFoundException":
                        logger.info(f"  새 시크릿 생성 필요")
                    else:
                        raise

                # 4. KMS 키 매핑
                src_kms_arn = src_secret_detail.get("KmsKeyId")
                dst_kms_arn = None

                if src_kms_arn:
                    dst_kms_arn = map_kms_key(src_kms_arn, dst_account)
                    if dst_kms_arn:
                        logger.info(f"  KMS 키 매핑: {src_kms_arn} -> {dst_kms_arn}")
                    else:
                        logger.info(f"  KMS 키: 기본 키 사용")

                # 5. 시크릿 생성 또는 업데이트
                if not dst_secret_exists:
                    # 새 시크릿 생성
                    logger.info(f"  새 시크릿 생성 중...")

                    create_params = {
                        "Name": secret_name
                    }

                    # Description
                    if src_secret_detail.get("Description"):
                        create_params["Description"] = src_secret_detail["Description"]

                    # KMS 키
                    if dst_kms_arn:
                        create_params["KmsKeyId"] = dst_kms_arn

                    # 시크릿 값
                    if secret_string:
                        create_params["SecretString"] = secret_string
                    elif secret_binary:
                        create_params["SecretBinary"] = secret_binary

                    # 태그
                    if src_secret_detail.get("Tags"):
                        create_params["Tags"] = src_secret_detail["Tags"]

                    response = sm_dst.create_secret(**create_params)
                    logger.info(f"  ✔ 시크릿 생성 완료: {response['ARN']}")
                    STATS["created"] += 1

                else:
                    # 기존 시크릿 업데이트
                    logger.info(f"  기존 시크릿 업데이트 중...")

                    # Description 업데이트
                    if src_secret_detail.get("Description"):
                        try:
                            sm_dst.update_secret(
                                SecretId=secret_name,
                                Description=src_secret_detail["Description"]
                            )
                            logger.info(f"  ✔ Description 업데이트 완료")
                        except Exception as e:
                            logger.warning(f"  [WARN] Description 업데이트 실패: {e}")

                    # KMS 키 업데이트
                    if dst_kms_arn:
                        try:
                            sm_dst.update_secret(
                                SecretId=secret_name,
                                KmsKeyId=dst_kms_arn
                            )
                            logger.info(f"  ✔ KMS 키 업데이트 완료")
                        except Exception as e:
                            logger.warning(f"  [WARN] KMS 키 업데이트 실패: {e}")

                    # 시크릿 값 업데이트
                    if secret_string or secret_binary:
                        update_params = {
                            "SecretId": secret_name
                        }

                        if secret_string:
                            update_params["SecretString"] = secret_string
                        elif secret_binary:
                            update_params["SecretBinary"] = secret_binary

                        sm_dst.put_secret_value(**update_params)
                        logger.info(f"  ✔ 시크릿 값 업데이트 완료")

                    STATS["updated"] += 1

                # 6. 태그 업데이트 (업데이트 케이스에서)
                if dst_secret_exists and src_secret_detail.get("Tags"):
                    try:
                        dst_secret_arn = f"arn:aws:secretsmanager:{REGION}:{dst_account}:secret:{secret_name}"

                        # 기존 태그 제거
                        try:
                            existing_tags = sm_dst.describe_secret(SecretId=secret_name).get("Tags", [])
                            if existing_tags:
                                tag_keys = [tag["Key"] for tag in existing_tags]
                                sm_dst.untag_resource(
                                    SecretId=secret_name,
                                    TagKeys=tag_keys
                                )
                        except Exception:
                            pass

                        # 새 태그 추가
                        sm_dst.tag_resource(
                            SecretId=secret_name,
                            Tags=src_secret_detail["Tags"]
                        )
                        logger.info(f"  ✔ 태그 업데이트 완료 ({len(src_secret_detail['Tags'])}개)")
                    except Exception as e:
                        logger.warning(f"  [WARN] 태그 업데이트 실패: {e}")

                # 7. 자동 회전 설정 복제 (선택적)
                if src_secret_detail.get("RotationEnabled"):
                    logger.info(f"  ⚠️  [주의] 소스 시크릿에 자동 회전이 활성화되어 있습니다")
                    logger.info(f"      자동 회전 설정은 Lambda 함수 ARN이 필요하므로 수동으로 설정해주세요")
                    logger.info(f"      회전 규칙: {src_secret_detail.get('RotationRules', {})}")
                    logger.info(f"      회전 Lambda ARN: {src_secret_detail.get('RotationLambdaARN', 'N/A')}")

            except Exception as e:
                logger.error(f"  ❌ 오류 발생: {secret_name} - {e}")
                import traceback
                logger.error(traceback.format_exc())
                STATS["failed"] += 1
                continue

    # 마이그레이션 완료 로그
    logger.info("\n" + "="*70)
    logger.info("✅ Secrets Manager 마이그레이션 완료!")
    logger.info("="*70)
    logger.info(f"📊 통계:")
    logger.info(f"  - 전체 시크릿: {STATS['total']}개")
    logger.info(f"  - 생성: {STATS['created']}개")
    logger.info(f"  - 업데이트: {STATS['updated']}개")
    logger.info(f"  - 실패: {STATS['failed']}개")
    logger.info(f"  - 스킵: {STATS['skipped']}개")
    logger.info("="*70)


# ===================================================
# 실행
# ===================================================
def main():
    logger.info("\n" + "="*70)
    logger.info("🔐 AWS Secrets Manager 마이그레이션 시작")
    logger.info("="*70)
    logger.info(f"소스 프로파일: {SRC_PROFILE}")
    logger.info(f"대상 프로파일: {DST_PROFILE}")
    logger.info(f"리전: {REGION}")
    logger.info(f"이름 접두사 필터: {NAME_PREFIX if NAME_PREFIX else '(전체)'}")
    logger.info("="*70)

    # KMS 키 매핑 로드
    global KMS_KEY_MAP
    try:
        if KMS_KEY_MAP_JSON:
            KMS_KEY_MAP = json.loads(KMS_KEY_MAP_JSON)
            logger.info(f"KMS 키 매핑 로드: {len(KMS_KEY_MAP)}개")
    except Exception as e:
        logger.warning(f"KMS 키 매핑 로드 실패: {e}")
        logger.warning("KMS 키 매핑이 없으면 기본 AWS 관리형 키를 사용합니다.")

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

    # Secrets Manager 클라이언트 생성
    sm_src = src_sess.client("secretsmanager")
    sm_dst = dst_sess.client("secretsmanager")

    try:
        # 시크릿 마이그레이션 실행
        migrate_secrets(sm_src, sm_dst, src_account, dst_account)

        # 추가 작업 안내
        if STATS["created"] > 0 or STATS["updated"] > 0:
            logger.info("\n⚠️  추가 확인 사항:")
            logger.info("1. 자동 회전 설정이 있는 시크릿은 수동으로 Lambda 함수를 설정해야 합니다")
            logger.info("2. KMS 키를 사용하는 경우, 대상 계정의 IAM 역할/사용자에게 KMS 키 권한이 있는지 확인하세요")
            logger.info("3. 리소스 정책이 있는 시크릿은 수동으로 정책을 검토하고 업데이트하세요")
            logger.info("4. VPC 엔드포인트를 사용하는 경우, 대상 계정에도 VPC 엔드포인트가 설정되어 있는지 확인하세요")

    except Exception as e:
        logger.error(f"\n❌ 마이그레이션 중 치명적 오류 발생: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
