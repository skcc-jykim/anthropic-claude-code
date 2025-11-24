#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
마이그레이션 체크리스트 CSV 템플릿 생성 스크립트

이 스크립트는 마이그레이션 대상 리소스 목록을 관리하기 위한
CSV 템플릿 파일을 생성합니다.
"""

import csv
import sys


def create_csv_template(filename: str = "migration_checklist_template.csv"):
    """
    마이그레이션 체크리스트 CSV 템플릿 생성
    """
    # 컬럼 헤더
    headers = [
        '리소스 타입',
        '리소스 이름',
        '소스 계정',
        '대상 계정',
        '마이그레이션 상태',
        '검증 일시',
        '비고'
    ]

    # 샘플 데이터
    sample_data = [
        ['Lambda', 'my-function-1', '111111111111', '222222222222', '', '', ''],
        ['Lambda', 'my-function-2', '111111111111', '222222222222', '', '', ''],
        ['StepFunction', 'my-state-machine', '111111111111', '222222222222', '', '', ''],
        ['EventBridgeRule', 'my-rule', '111111111111', '222222222222', '', '', ''],
        ['EventBridgeSchedule', 'default/my-schedule', '111111111111', '222222222222', '', '', '스케줄 그룹명/스케줄명 형식'],
        ['APIGateway', 'my-api', '111111111111', '222222222222', '', '', ''],
        ['SecretsManager', 'my-secret', '111111111111', '222222222222', '', '', ''],
    ]

    try:
        # CSV 파일 작성 (UTF-8 인코딩)
        with open(filename, 'w', newline='', encoding='utf-8-sig') as csvfile:
            writer = csv.writer(csvfile)

            # 헤더 작성
            writer.writerow(headers)

            # 샘플 데이터 작성
            writer.writerows(sample_data)

            # 빈 행 추가 (사용자가 입력할 공간)
            for _ in range(10):
                writer.writerow([''] * len(headers))

        print(f"✅ CSV 템플릿 파일이 생성되었습니다: {filename}")
        print(f"")
        print(f"사용 방법:")
        print(f"1. {filename} 파일을 열어서 마이그레이션 대상 리소스를 입력하세요")
        print(f"2. 입력이 완료되면 파일을 'migration_checklist.csv'로 저장하세요")
        print(f"3. verify_migration_from_excel.py 스크립트도 CSV를 지원합니다")
        print(f"")
        print_usage_instructions()

    except Exception as e:
        print(f"❌ 오류가 발생했습니다: {e}")
        sys.exit(1)


def print_usage_instructions():
    """
    사용 방법 출력
    """
    print("=" * 80)
    print("📋 마이그레이션 체크리스트 사용 방법")
    print("=" * 80)
    print("")
    print("1. 기본 정보")
    print("   이 CSV 파일은 AWS 리소스 마이그레이션 대상을 관리하고")
    print("   실제 이관 완료 여부를 검증하기 위한 체크리스트입니다.")
    print("")
    print("2. 컬럼 설명")
    print("   • 리소스 타입: Lambda, StepFunction, EventBridgeRule,")
    print("                  EventBridgeSchedule, APIGateway, SecretsManager")
    print("   • 리소스 이름: AWS 리소스의 이름 (ARN 아님)")
    print("   • 소스 계정: 소스 AWS 계정 ID (12자리 숫자)")
    print("   • 대상 계정: 대상 AWS 계정 ID (12자리 숫자)")
    print("   • 마이그레이션 상태: 검증 스크립트가 자동으로 업데이트")
    print("   • 검증 일시: 검증 스크립트가 자동으로 업데이트")
    print("   • 비고: 검증 스크립트가 자동으로 업데이트 (또는 수동 메모)")
    print("")
    print("3. 리소스 타입별 이름 형식")
    print("   • Lambda: 함수 이름 (예: my-function)")
    print("   • StepFunction: 상태 머신 이름 (예: my-state-machine)")
    print("   • EventBridgeRule: 규칙 이름 (예: my-rule)")
    print("   • EventBridgeSchedule: 그룹명/스케줄명 (예: default/my-schedule)")
    print("                          또는 스케줄명만")
    print("   • APIGateway: REST API 이름 (예: my-api)")
    print("   • SecretsManager: 시크릿 이름 (예: my-secret)")
    print("")
    print("4. 검증 스크립트 실행")
    print("   python3 verify_migration_from_excel.py")
    print("")
    print("   환경변수 설정:")
    print("   export DST_PROFILE=dst              # 대상 계정 AWS 프로파일")
    print("   export AWS_REGION=ap-northeast-2    # AWS 리전")
    print("   export EXCEL_FILE_PATH=migration_checklist.csv  # 입력 CSV 파일")
    print("   export OUTPUT_FILE_PATH=migration_verification_result.csv  # 출력 파일")
    print("")
    print("5. 주의사항")
    print("   • CSV 파일을 Excel에서 열 때 UTF-8 인코딩으로 열어야 합니다")
    print("   • 헤더 행(첫 번째 행)을 삭제하지 마세요")
    print("   • 리소스 타입은 정확하게 입력해야 합니다 (대소문자 구분)")
    print("   • 쉼표(,)가 포함된 값은 큰따옴표로 감싸야 합니다")
    print("")
    print("=" * 80)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='마이그레이션 체크리스트 CSV 템플릿 생성')
    parser.add_argument(
        '-o', '--output',
        default='migration_checklist_template.csv',
        help='출력 파일명 (기본값: migration_checklist_template.csv)'
    )

    args = parser.parse_args()
    create_csv_template(args.output)
