#!/bin/bash
# 특정 리소스 마이그레이션 실행 스크립트

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}🎯 특정 리소스 마이그레이션 스크립트${NC}"
echo -e "${BLUE}========================================${NC}"
echo

# 환경 변수 확인
if [ -z "$SRC_PROFILE" ]; then
    echo -e "${RED}❌ SRC_PROFILE 환경 변수가 설정되지 않았습니다${NC}"
    echo -e "${YELLOW}사용법: export SRC_PROFILE=src${NC}"
    exit 1
fi

if [ -z "$DST_PROFILE" ]; then
    echo -e "${RED}❌ DST_PROFILE 환경 변수가 설정되지 않았습니다${NC}"
    echo -e "${YELLOW}사용법: export DST_PROFILE=dst${NC}"
    exit 1
fi

# AWS 리전 기본값
if [ -z "$AWS_REGION" ]; then
    export AWS_REGION="ap-northeast-2"
    echo -e "${YELLOW}ℹ️  AWS_REGION이 설정되지 않아 기본값 사용: ap-northeast-2${NC}"
fi

echo -e "${GREEN}✅ 환경 변수 확인 완료${NC}"
echo -e "  소스 프로파일: ${SRC_PROFILE}"
echo -e "  대상 프로파일: ${DST_PROFILE}"
echo -e "  리전: ${AWS_REGION}"
echo

# Python 확인
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3가 설치되어 있지 않습니다${NC}"
    exit 1
fi

# boto3 확인
if ! python3 -c "import boto3" 2>/dev/null; then
    echo -e "${RED}❌ boto3가 설치되어 있지 않습니다${NC}"
    echo -e "${YELLOW}설치 방법: pip install boto3 requests${NC}"
    exit 1
fi

# Docker 확인 (경고만)
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}⚠️  Docker가 설치되어 있지 않습니다${NC}"
    echo -e "${YELLOW}   컨테이너 이미지 Lambda 마이그레이션을 건너뛸 수 있습니다${NC}"
    echo
fi

# 스크립트 디렉토리로 이동
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 리소스 파일 확인
echo -e "${BLUE}📋 리소스 목록 파일 확인${NC}"

if [ ! -f "target_lambdas.txt" ]; then
    echo -e "${RED}❌ target_lambdas.txt를 찾을 수 없습니다${NC}"
    exit 1
fi

if [ ! -f "target_stepfunctions.txt" ]; then
    echo -e "${RED}❌ target_stepfunctions.txt를 찾을 수 없습니다${NC}"
    exit 1
fi

if [ ! -f "target_schedules.txt" ]; then
    echo -e "${RED}❌ target_schedules.txt를 찾을 수 없습니다${NC}"
    exit 1
fi

echo -e "${GREEN}✅ 모든 리소스 목록 파일 존재 확인${NC}"
echo

# 마이그레이션 모드 선택
echo -e "${BLUE}마이그레이션 모드를 선택하세요:${NC}"
echo "  1) 전체 마이그레이션 (Lambda + StepFunctions + Schedules)"
echo "  2) 검증만 수행 (실제 마이그레이션 없음)"
echo "  3) Lambda만 마이그레이션"
echo "  4) StepFunctions만 마이그레이션"
echo "  5) Schedules만 마이그레이션"
echo

read -p "선택 (1-5): " mode

case $mode in
    1)
        echo -e "\n${GREEN}🚀 전체 마이그레이션을 시작합니다...${NC}\n"
        python3 migrate_specific_resources_runner.py
        ;;
    2)
        echo -e "\n${GREEN}🔍 검증을 시작합니다...${NC}\n"
        python3 migrate_specific_resources.py
        ;;
    3)
        echo -e "\n${GREEN}🚀 Lambda 마이그레이션을 시작합니다...${NC}\n"
        # target_stepfunctions.txt와 target_schedules.txt를 임시로 백업
        mv target_stepfunctions.txt target_stepfunctions.txt.bak 2>/dev/null || true
        mv target_schedules.txt target_schedules.txt.bak 2>/dev/null || true
        touch target_stepfunctions.txt target_schedules.txt

        python3 migrate_specific_resources_runner.py

        # 백업 복원
        mv target_stepfunctions.txt.bak target_stepfunctions.txt 2>/dev/null || true
        mv target_schedules.txt.bak target_schedules.txt 2>/dev/null || true
        ;;
    4)
        echo -e "\n${GREEN}🚀 StepFunctions 마이그레이션을 시작합니다...${NC}\n"
        # target_lambdas.txt와 target_schedules.txt를 임시로 백업
        mv target_lambdas.txt target_lambdas.txt.bak 2>/dev/null || true
        mv target_schedules.txt target_schedules.txt.bak 2>/dev/null || true
        touch target_lambdas.txt target_schedules.txt

        python3 migrate_specific_resources_runner.py

        # 백업 복원
        mv target_lambdas.txt.bak target_lambdas.txt 2>/dev/null || true
        mv target_schedules.txt.bak target_schedules.txt 2>/dev/null || true
        ;;
    5)
        echo -e "\n${GREEN}🚀 Schedules 마이그레이션을 시작합니다...${NC}\n"
        # target_lambdas.txt와 target_stepfunctions.txt를 임시로 백업
        mv target_lambdas.txt target_lambdas.txt.bak 2>/dev/null || true
        mv target_stepfunctions.txt target_stepfunctions.txt.bak 2>/dev/null || true
        touch target_lambdas.txt target_stepfunctions.txt

        python3 migrate_specific_resources_runner.py

        # 백업 복원
        mv target_lambdas.txt.bak target_lambdas.txt 2>/dev/null || true
        mv target_stepfunctions.txt.bak target_stepfunctions.txt 2>/dev/null || true
        ;;
    *)
        echo -e "${RED}❌ 잘못된 선택입니다${NC}"
        exit 1
        ;;
esac

echo
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✅ 완료!${NC}"
echo -e "${GREEN}========================================${NC}"
