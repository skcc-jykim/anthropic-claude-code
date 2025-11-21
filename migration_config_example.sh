#!/bin/bash
# AWS 리소스 마이그레이션 설정 예제
# 이 파일을 복사하여 실제 값으로 수정 후 사용하세요

# ===================================================
# 기본 설정
# ===================================================

# AWS 프로파일 이름
export SRC_PROFILE="source-account-profile"
export DST_PROFILE="destination-account-profile"

# 리전
export AWS_REGION="ap-northeast-2"

# 마이그레이션할 리소스 이름 필터 (선택적)
# 특정 접두사를 가진 리소스만 마이그레이션하려면 설정
# 예: "prod-", "service-name-"
export NAME_PREFIX=""

# ===================================================
# IAM Role 설정
# ===================================================

# Lambda 함수 기본 실행 Role
export DEFAULT_DEST_LAMBDA_ROLE="arn:aws:iam::TARGET_ACCOUNT_ID:role/lambda-execution-role"

# Step Functions 기본 실행 Role
export DEFAULT_DEST_SFN_ROLE="arn:aws:iam::TARGET_ACCOUNT_ID:role/stepfunctions-execution-role"

# ===================================================
# 실행
# ===================================================

echo "=========================================="
echo "AWS 리소스 마이그레이션 시작"
echo "=========================================="
echo "소스 프로파일: $SRC_PROFILE"
echo "대상 프로파일: $DST_PROFILE"
echo "리전: $AWS_REGION"
echo "이름 필터: ${NAME_PREFIX:-'(전체)'}"
echo "=========================================="
echo ""
echo "계속하려면 Enter를 누르세요 (취소: Ctrl+C)"
read

# 마이그레이션 실행
python3 migrate_aws_resources.py

echo ""
echo "=========================================="
echo "마이그레이션 완료!"
echo "=========================================="
