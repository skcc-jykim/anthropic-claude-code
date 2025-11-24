#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
특정 리소스만 마이그레이션하는 전용 스크립트

대상 리소스:
- Lambda: target_lambdas.txt
- StepFunction: target_stepfunctions.txt
- EventBridge Schedules: target_schedules.txt

사용법:
    export SRC_PROFILE=src
    export DST_PROFILE=dst
    python migrate_specific_resources.py
"""

import os
import sys
import logging
from pathlib import Path

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


def load_resource_list(file_path: Path) -> set:
    """리소스 목록 파일 로드"""
    resources = set()

    if not file_path.exists():
        logger.error(f"❌ 리소스 목록 파일을 찾을 수 없습니다: {file_path}")
        return resources

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # 빈 줄이나 주석(#으로 시작) 무시
                if line and not line.startswith('#'):
                    resources.add(line)

        logger.info(f"📋 리소스 목록 로드 완료: {file_path.name} ({len(resources)}개)")
        return resources

    except Exception as e:
        logger.error(f"❌ 리소스 목록 파일 읽기 실패: {e}")
        return set()


def create_lambda_filter_file(lambda_list: set, output_file: str = "lambda_functions_to_migrate.txt"):
    """Lambda 함수 목록을 필터 파일로 저장"""
    output_path = SCRIPT_DIR / output_file

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("# Lambda functions to migrate\n")
        f.write("# Generated for selective migration\n\n")
        for func in sorted(lambda_list):
            f.write(f"{func}\n")

    logger.info(f"✅ Lambda 필터 파일 생성 완료: {output_path}")
    return str(output_path)


def main():
    logger.info("\n" + "="*70)
    logger.info("🎯 특정 리소스 마이그레이션 준비")
    logger.info("="*70)

    # 1. 리소스 목록 로드
    logger.info("\n📂 리소스 목록 로드 중...")

    lambda_list = load_resource_list(TARGET_LAMBDAS_FILE)
    stepfunctions_list = load_resource_list(TARGET_STEPFUNCTIONS_FILE)
    schedules_list = load_resource_list(TARGET_SCHEDULES_FILE)

    if not lambda_list and not stepfunctions_list and not schedules_list:
        logger.error("❌ 마이그레이션할 리소스가 없습니다!")
        return 1

    # 2. 요약 출력
    logger.info("\n" + "="*70)
    logger.info("📊 마이그레이션 대상 리소스 요약")
    logger.info("="*70)
    logger.info(f"🚀 Lambda 함수: {len(lambda_list)}개")
    logger.info(f"⚙️  Step Functions: {len(stepfunctions_list)}개")
    logger.info(f"⏰ EventBridge Schedules: {len(schedules_list)}개")
    logger.info(f"📦 총 리소스: {len(lambda_list) + len(stepfunctions_list) + len(schedules_list)}개")
    logger.info("="*70)

    # 3. Lambda 필터 파일 생성
    if lambda_list:
        lambda_filter_file = create_lambda_filter_file(lambda_list)
        logger.info(f"\n💡 Lambda 마이그레이션 명령:")
        logger.info(f"   export LAMBDA_FUNCTIONS_FILE={lambda_filter_file}")
        logger.info(f"   python migrate_aws_resources.py")

    # 4. Step Functions 필터링 가이드
    if stepfunctions_list:
        logger.info(f"\n💡 Step Functions 마이그레이션:")
        logger.info(f"   대상 상태 머신: {len(stepfunctions_list)}개")
        logger.info(f"   - {', '.join(list(stepfunctions_list)[:5])}...")
        logger.info(f"   ℹ️  migrate_aws_resources.py는 NAME_PREFIX로 필터링하거나")
        logger.info(f"   ℹ️  수동으로 마이그레이션 스크립트를 수정해야 합니다")

    # 5. Schedules 필터링 가이드
    if schedules_list:
        logger.info(f"\n💡 EventBridge Schedules 마이그레이션:")
        logger.info(f"   대상 일정: {len(schedules_list)}개")

        # 그룹별로 분류
        groups = {}
        for schedule in schedules_list:
            if '/' in schedule:
                group, name = schedule.split('/', 1)
                if group not in groups:
                    groups[group] = []
                groups[group].append(name)
            else:
                if 'default' not in groups:
                    groups['default'] = []
                groups['default'].append(schedule)

        logger.info(f"\n   그룹별 분류:")
        for group, names in sorted(groups.items()):
            logger.info(f"   - {group}: {len(names)}개")

    # 6. 통합 마이그레이션 가이드
    logger.info("\n" + "="*70)
    logger.info("🚀 마이그레이션 실행 가이드")
    logger.info("="*70)
    logger.info("""
방법 1: 환경 변수를 사용한 Lambda 선택적 마이그레이션
    export SRC_PROFILE=src
    export DST_PROFILE=dst
    export LAMBDA_FUNCTIONS_FILE=lambda_functions_to_migrate.txt
    python migrate_aws_resources.py

방법 2: 수정된 마이그레이션 스크립트 사용 (추천)
    이 스크립트는 target_*.txt 파일을 직접 참조하여
    Lambda, StepFunction, Schedules를 모두 필터링합니다.

    아래 명령으로 실행:
    export SRC_PROFILE=src
    export DST_PROFILE=dst
    python migrate_specific_resources_runner.py

참고사항:
    - Layer는 자동으로 마이그레이션됩니다 (Lambda가 의존하는 Layer)
    - EventBridge Rules는 기본적으로 마이그레이션되지 않습니다
    - Schedule Groups는 자동으로 생성됩니다
    """)

    logger.info("="*70)
    logger.info("✅ 준비 완료!")
    logger.info("="*70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
