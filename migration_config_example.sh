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
# Lambda 선택적 마이그레이션 설정 (선택적)
# ===================================================

# 방법 1: 쉼표로 구분된 Lambda 함수 이름 목록
# 예: "function1,function2,function3"
# export LAMBDA_FUNCTIONS="my-function-1,my-function-2,my-function-3"

# 방법 2: Lambda 함수 목록이 담긴 파일 경로
# 파일 형식: 한 줄에 하나씩 또는 쉼표로 구분
# 주석(#으로 시작)과 빈 줄은 무시됩니다
# export LAMBDA_FUNCTIONS_FILE="lambda_functions.txt"

# 방법 3: 제외할 Lambda 함수 패턴 (쉼표로 구분)
# 함수 이름에 패턴이 포함되면 제외됩니다
# 예: "test,dev,backup"
# export LAMBDA_EXCLUDE_PATTERN="test,dev"

# 참고:
# - LAMBDA_FUNCTIONS_FILE이 설정되면 LAMBDA_FUNCTIONS는 무시됩니다
# - NAME_PREFIX와 함께 사용 가능 (AND 조건)
# - 세 가지 방법을 모두 사용할 수 있습니다

# ===================================================
# IAM Role 설정
# ===================================================

# Lambda 함수 기본 실행 Role
export DEFAULT_DEST_LAMBDA_ROLE="arn:aws:iam::TARGET_ACCOUNT_ID:role/lambda-execution-role"

# Step Functions 기본 실행 Role
export DEFAULT_DEST_SFN_ROLE="arn:aws:iam::TARGET_ACCOUNT_ID:role/stepfunctions-execution-role"

# EventBridge Rules 실행 Role (선택적)
# 환경변수로 제공하면 자동 생성을 스킵하고 제공된 Role 사용
# export EVENTBRIDGE_RULES_ROLE_ARN="arn:aws:iam::TARGET_ACCOUNT_ID:role/EventBridgeRulesExecutionRole"

# EventBridge Scheduler 실행 Role (선택적)
# 환경변수로 제공하면 자동 생성을 스킵하고 제공된 Role 사용
# export EVENTBRIDGE_SCHEDULER_ROLE_ARN="arn:aws:iam::TARGET_ACCOUNT_ID:role/EventBridgeSchedulerExecutionRole"

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
if [ -n "$LAMBDA_FUNCTIONS" ]; then
    echo "Lambda 필터 (목록): $LAMBDA_FUNCTIONS"
elif [ -n "$LAMBDA_FUNCTIONS_FILE" ]; then
    echo "Lambda 필터 (파일): $LAMBDA_FUNCTIONS_FILE"
fi
if [ -n "$LAMBDA_EXCLUDE_PATTERN" ]; then
    echo "Lambda 제외 패턴: $LAMBDA_EXCLUDE_PATTERN"
fi
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
