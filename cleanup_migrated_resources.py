#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import boto3
import logging
import time
from botocore.exceptions import ClientError
from typing import List, Set

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


def confirm_deletion() -> bool:
    """사용자 확인 입력"""
    response = input("\n⚠️  위 리소스들을 모두 삭제하시겠습니까? (yes/no): ").strip().lower()
    return response in ['yes', 'y']


# ===================================================
# EventBridge 규칙 삭제
# ===================================================
@retry_on_throttle
def cleanup_eventbridge_rules(events_src, events_dst) -> int:
    """EventBridge 규칙 삭제"""

    logger.info("\n" + "="*50)
    logger.info("🗑️  EventBridge 규칙 삭제 시작")
    logger.info("="*50)

    deleted_count = 0
    event_buses = ["default"]

    for bus_name in event_buses:
        logger.info(f"\n이벤트 버스: {bus_name}")

        paginator = events_src.get_paginator("list_rules")

        for page in paginator.paginate(EventBusName=bus_name):
            for rule in page.get("Rules", []):
                rule_name = rule["Name"]

                if NAME_PREFIX and not rule_name.startswith(NAME_PREFIX):
                    continue

                try:
                    # 대상 계정에 규칙이 존재하는지 확인
                    try:
                        events_dst.describe_rule(Name=rule_name, EventBusName=bus_name)
                    except ClientError as e:
                        if e.response["Error"]["Code"] == "ResourceNotFoundException":
                            logger.debug(f"  [SKIP] {rule_name} (대상 계정에 존재하지 않음)")
                            continue
                        raise

                    logger.info(f"  🗑️  삭제 중: {rule_name}")

                    # 타겟 먼저 제거
                    targets = events_dst.list_targets_by_rule(Rule=rule_name, EventBusName=bus_name)
                    if targets.get("Targets"):
                        target_ids = [t["Id"] for t in targets["Targets"]]
                        events_dst.remove_targets(
                            Rule=rule_name,
                            EventBusName=bus_name,
                            Ids=target_ids
                        )
                        logger.info(f"    ✔ 타겟 제거 완료 ({len(target_ids)}개)")

                    # 규칙 삭제
                    events_dst.delete_rule(Name=rule_name, EventBusName=bus_name)
                    logger.info(f"    ✔ 규칙 삭제 완료: {rule_name}")
                    deleted_count += 1

                except Exception as e:
                    logger.error(f"  ❌ 오류 발생: {rule_name} - {e}")
                    continue

    logger.info(f"\n🗑️  EventBridge 규칙 삭제 완료! (총 {deleted_count}개)")
    return deleted_count


# ===================================================
# EventBridge Scheduler 삭제
# ===================================================
@retry_on_throttle
def cleanup_schedules(scheduler_src, scheduler_dst) -> int:
    """EventBridge Scheduler 일정 삭제"""

    logger.info("\n" + "="*50)
    logger.info("🗑️  EventBridge Scheduler 일정 삭제 시작")
    logger.info("="*50)

    deleted_count = 0

    try:
        # 모든 Schedule Groups에서 일정 가져오기
        group_names = ["default"]

        # 사용자 정의 그룹 추가
        try:
            paginator = scheduler_src.get_paginator("list_schedule_groups")
            for page in paginator.paginate():
                for group in page.get("ScheduleGroups", []):
                    group_name = group["Name"]
                    if group_name != "default":
                        if not NAME_PREFIX or group_name.startswith(NAME_PREFIX):
                            group_names.append(group_name)
        except Exception as e:
            logger.warning(f"  [WARN] Schedule Groups 목록 가져오기 실패: {e}")

        # 각 그룹의 일정 삭제
        for group_name in group_names:
            logger.info(f"\n그룹: {group_name}")

            try:
                paginator = scheduler_src.get_paginator("list_schedules")

                for page in paginator.paginate(GroupName=group_name):
                    for schedule in page.get("Schedules", []):
                        schedule_name = schedule["Name"]

                        if NAME_PREFIX and not schedule_name.startswith(NAME_PREFIX):
                            continue

                        try:
                            # 대상 계정에 일정이 존재하는지 확인
                            try:
                                scheduler_dst.get_schedule(Name=schedule_name, GroupName=group_name)
                            except ClientError as e:
                                if e.response["Error"]["Code"] == "ResourceNotFoundException":
                                    logger.debug(f"  [SKIP] {schedule_name} (대상 계정에 존재하지 않음)")
                                    continue
                                raise

                            logger.info(f"  🗑️  삭제 중: {schedule_name}")

                            # 일정 삭제
                            scheduler_dst.delete_schedule(Name=schedule_name, GroupName=group_name)
                            logger.info(f"    ✔ 삭제 완료: {schedule_name}")
                            deleted_count += 1

                        except Exception as e:
                            logger.error(f"  ❌ 오류 발생: {schedule_name} - {e}")
                            continue

            except Exception as e:
                logger.error(f"  ❌ 그룹 {group_name}의 일정 처리 실패: {e}")
                continue

        logger.info(f"\n🗑️  Schedules 삭제 완료! (총 {deleted_count}개)")
        return deleted_count

    except Exception as e:
        logger.error(f"❌ Schedules 삭제 실패: {e}")
        return deleted_count


@retry_on_throttle
def cleanup_schedule_groups(scheduler_src, scheduler_dst) -> int:
    """EventBridge Scheduler 그룹 삭제"""

    logger.info("\n" + "="*50)
    logger.info("🗑️  EventBridge Scheduler 그룹 삭제 시작")
    logger.info("="*50)

    deleted_count = 0

    try:
        paginator = scheduler_src.get_paginator("list_schedule_groups")

        for page in paginator.paginate():
            for group in page.get("ScheduleGroups", []):
                group_name = group["Name"]

                if NAME_PREFIX and not group_name.startswith(NAME_PREFIX):
                    continue

                # 'default' 그룹은 삭제할 수 없음
                if group_name == "default":
                    logger.info(f"  [SKIP] default 그룹은 삭제할 수 없음")
                    continue

                try:
                    # 대상 계정에 그룹이 존재하는지 확인
                    try:
                        scheduler_dst.get_schedule_group(Name=group_name)
                    except ClientError as e:
                        if e.response["Error"]["Code"] == "ResourceNotFoundException":
                            logger.debug(f"  [SKIP] {group_name} (대상 계정에 존재하지 않음)")
                            continue
                        raise

                    logger.info(f"  🗑️  삭제 중: {group_name}")

                    # 그룹 삭제
                    scheduler_dst.delete_schedule_group(Name=group_name)
                    logger.info(f"    ✔ 삭제 완료: {group_name}")
                    deleted_count += 1

                except Exception as e:
                    logger.error(f"  ❌ 오류 발생: {group_name} - {e}")
                    continue

        logger.info(f"\n🗑️  Schedule Groups 삭제 완료! (총 {deleted_count}개)")
        return deleted_count

    except Exception as e:
        logger.error(f"❌ Schedule Groups 삭제 실패: {e}")
        return deleted_count


# ===================================================
# Step Functions 삭제
# ===================================================
@retry_on_throttle
def cleanup_step_functions(sfn_src, sfn_dst) -> int:
    """Step Functions 상태 머신 삭제"""

    logger.info("\n" + "="*50)
    logger.info("🗑️  Step Functions 삭제 시작")
    logger.info("="*50)

    deleted_count = 0
    paginator = sfn_src.get_paginator("list_state_machines")

    for page in paginator.paginate():
        for sm in page.get("stateMachines", []):
            sm_name = sm["name"]

            if NAME_PREFIX and not sm_name.startswith(NAME_PREFIX):
                continue

            try:
                # 대상 계정에서 동일 이름의 상태 머신 찾기
                dst_sm_list = sfn_dst.list_state_machines()
                dst_sm_arn = None

                for dst_sm in dst_sm_list.get("stateMachines", []):
                    if dst_sm["name"] == sm_name:
                        dst_sm_arn = dst_sm["stateMachineArn"]
                        break

                if not dst_sm_arn:
                    logger.debug(f"  [SKIP] {sm_name} (대상 계정에 존재하지 않음)")
                    continue

                logger.info(f"  🗑️  삭제 중: {sm_name}")

                # 상태 머신 삭제
                sfn_dst.delete_state_machine(stateMachineArn=dst_sm_arn)
                logger.info(f"    ✔ 삭제 완료: {sm_name}")
                deleted_count += 1

            except Exception as e:
                logger.error(f"  ❌ 오류 발생: {sm_name} - {e}")
                continue

    logger.info(f"\n🗑️  Step Functions 삭제 완료! (총 {deleted_count}개)")
    return deleted_count


# ===================================================
# Lambda 함수 삭제
# ===================================================
@retry_on_throttle
def cleanup_lambda_functions(lambda_src, lambda_dst) -> int:
    """Lambda 함수 삭제"""

    logger.info("\n" + "="*50)
    logger.info("🗑️  Lambda 함수 삭제 시작")
    logger.info("="*50)

    deleted_count = 0
    paginator = lambda_src.get_paginator("list_functions")

    for page in paginator.paginate():
        for fn in page["Functions"]:
            name = fn["FunctionName"]

            if NAME_PREFIX and not name.startswith(NAME_PREFIX):
                continue

            try:
                # 대상 계정에 함수가 존재하는지 확인
                try:
                    lambda_dst.get_function(FunctionName=name)
                except ClientError as e:
                    if e.response["Error"]["Code"] == "ResourceNotFoundException":
                        logger.debug(f"  [SKIP] {name} (대상 계정에 존재하지 않음)")
                        continue
                    raise

                logger.info(f"  🗑️  삭제 중: {name}")

                # Lambda 함수 삭제
                lambda_dst.delete_function(FunctionName=name)
                logger.info(f"    ✔ 삭제 완료: {name}")
                deleted_count += 1

            except Exception as e:
                logger.error(f"  ❌ 오류 발생: {name} - {e}")
                continue

    logger.info(f"\n🗑️  Lambda 함수 삭제 완료! (총 {deleted_count}개)")
    return deleted_count


# ===================================================
# Lambda Layer 삭제
# ===================================================
@retry_on_throttle
def cleanup_lambda_layers(lambda_src, lambda_dst) -> int:
    """Lambda Layer 삭제"""

    logger.info("\n" + "="*50)
    logger.info("🗑️  Lambda Layer 삭제 시작")
    logger.info("="*50)

    deleted_count = 0
    deleted_layers: Set[str] = set()

    paginator = lambda_src.get_paginator("list_layers")

    for page in paginator.paginate():
        for layer in page.get("Layers", []):
            layer_name = layer["LayerName"]

            if layer_name in deleted_layers:
                continue

            try:
                # 대상 계정에 Layer가 존재하는지 확인
                try:
                    dst_versions = lambda_dst.list_layer_versions(LayerName=layer_name)
                except ClientError as e:
                    if e.response["Error"]["Code"] == "ResourceNotFoundException":
                        logger.debug(f"  [SKIP] {layer_name} (대상 계정에 존재하지 않음)")
                        continue
                    raise

                if not dst_versions.get("LayerVersions"):
                    logger.debug(f"  [SKIP] {layer_name} (버전 없음)")
                    continue

                logger.info(f"  🗑️  삭제 중: {layer_name}")

                # 모든 버전 삭제
                version_count = 0
                for version in dst_versions["LayerVersions"]:
                    version_number = version["Version"]
                    lambda_dst.delete_layer_version(
                        LayerName=layer_name,
                        VersionNumber=version_number
                    )
                    version_count += 1

                logger.info(f"    ✔ 삭제 완료: {layer_name} ({version_count}개 버전)")
                deleted_layers.add(layer_name)
                deleted_count += 1

            except Exception as e:
                logger.error(f"  ❌ 오류 발생: {layer_name} - {e}")
                continue

    logger.info(f"\n🗑️  Lambda Layer 삭제 완료! (총 {deleted_count}개)")
    return deleted_count


# ===================================================
# 리소스 목록 미리보기
# ===================================================
def preview_resources(lambda_src, sfn_src, events_src, scheduler_src) -> dict:
    """삭제될 리소스 목록 미리보기"""

    logger.info("\n" + "="*50)
    logger.info("📋 삭제될 리소스 미리보기")
    logger.info("="*50)

    resources = {
        "layers": [],
        "lambdas": [],
        "step_functions": [],
        "eventbridge_rules": [],
        "schedules": [],
        "schedule_groups": []
    }

    # Lambda Layers
    paginator = lambda_src.get_paginator("list_layers")
    for page in paginator.paginate():
        for layer in page.get("Layers", []):
            resources["layers"].append(layer["LayerName"])

    # Lambda Functions
    paginator = lambda_src.get_paginator("list_functions")
    for page in paginator.paginate():
        for fn in page["Functions"]:
            name = fn["FunctionName"]
            if NAME_PREFIX and not name.startswith(NAME_PREFIX):
                continue
            resources["lambdas"].append(name)

    # Step Functions
    paginator = sfn_src.get_paginator("list_state_machines")
    for page in paginator.paginate():
        for sm in page.get("stateMachines", []):
            name = sm["name"]
            if NAME_PREFIX and not name.startswith(NAME_PREFIX):
                continue
            resources["step_functions"].append(name)

    # EventBridge Rules
    paginator = events_src.get_paginator("list_rules")
    for page in paginator.paginate(EventBusName="default"):
        for rule in page.get("Rules", []):
            name = rule["Name"]
            if NAME_PREFIX and not name.startswith(NAME_PREFIX):
                continue
            resources["eventbridge_rules"].append(name)

    # EventBridge Schedules
    try:
        group_names = ["default"]
        try:
            paginator = scheduler_src.get_paginator("list_schedule_groups")
            for page in paginator.paginate():
                for group in page.get("ScheduleGroups", []):
                    group_name = group["Name"]
                    if group_name != "default":
                        if not NAME_PREFIX or group_name.startswith(NAME_PREFIX):
                            group_names.append(group_name)
                            resources["schedule_groups"].append(group_name)
        except Exception:
            pass

        for group_name in group_names:
            try:
                paginator = scheduler_src.get_paginator("list_schedules")
                for page in paginator.paginate(GroupName=group_name):
                    for schedule in page.get("Schedules", []):
                        schedule_name = schedule["Name"]
                        if NAME_PREFIX and not schedule_name.startswith(NAME_PREFIX):
                            continue
                        resources["schedules"].append(f"{schedule_name} (그룹: {group_name})")
            except Exception:
                pass
    except Exception:
        pass

    # 출력
    logger.info(f"\n📦 Lambda Layers: {len(resources['layers'])}개")
    for name in resources["layers"]:
        logger.info(f"  - {name}")

    logger.info(f"\n⚡ Lambda Functions: {len(resources['lambdas'])}개")
    for name in resources["lambdas"]:
        logger.info(f"  - {name}")

    logger.info(f"\n⚙️  Step Functions: {len(resources['step_functions'])}개")
    for name in resources["step_functions"]:
        logger.info(f"  - {name}")

    logger.info(f"\n📅 EventBridge Rules: {len(resources['eventbridge_rules'])}개")
    for name in resources["eventbridge_rules"]:
        logger.info(f"  - {name}")

    logger.info(f"\n⏰ EventBridge Schedules: {len(resources['schedules'])}개")
    for name in resources["schedules"]:
        logger.info(f"  - {name}")

    logger.info(f"\n📁 EventBridge Schedule Groups: {len(resources['schedule_groups'])}개")
    for name in resources["schedule_groups"]:
        logger.info(f"  - {name}")

    logger.info("\n" + "="*50)

    return resources


# ===================================================
# 실행
# ===================================================
def main():
    logger.info("\n" + "="*70)
    logger.info("🗑️  AWS 리소스 정리 (Cleanup) 시작")
    logger.info("="*70)
    logger.info(f"소스 프로파일: {SRC_PROFILE}")
    logger.info(f"대상 프로파일: {DST_PROFILE}")
    logger.info(f"리전: {REGION}")
    logger.info(f"이름 접두사 필터: {NAME_PREFIX if NAME_PREFIX else '(전체)'}")
    logger.info("="*70)

    # 세션 생성
    src_sess = boto3.Session(profile_name=SRC_PROFILE, region_name=REGION)
    dst_sess = boto3.Session(profile_name=DST_PROFILE, region_name=REGION)

    # 계정 ID 확인
    src_sts = src_sess.client("sts")
    dst_sts = dst_sess.client("sts")
    src_account = src_sts.get_caller_identity()["Account"]
    dst_account = dst_sts.get_caller_identity()["Account"]

    logger.info(f"소스 계정: {src_account}")
    logger.info(f"대상 계정: {dst_account} (여기서 리소스 삭제됨)")

    # 클라이언트 생성
    lambda_src = src_sess.client("lambda")
    lambda_dst = dst_sess.client("lambda")
    sfn_src = src_sess.client("stepfunctions")
    sfn_dst = dst_sess.client("stepfunctions")
    events_src = src_sess.client("events")
    events_dst = dst_sess.client("events")
    scheduler_src = src_sess.client("scheduler")
    scheduler_dst = dst_sess.client("scheduler")

    try:
        # 리소스 미리보기
        resources = preview_resources(lambda_src, sfn_src, events_src, scheduler_src)

        total_resources = (
            len(resources["layers"]) +
            len(resources["lambdas"]) +
            len(resources["step_functions"]) +
            len(resources["eventbridge_rules"]) +
            len(resources["schedules"]) +
            len(resources["schedule_groups"])
        )

        if total_resources == 0:
            logger.info("\n✅ 삭제할 리소스가 없습니다.")
            return

        # 사용자 확인
        if not confirm_deletion():
            logger.info("\n❌ 사용자가 삭제를 취소했습니다.")
            return

        logger.info("\n🗑️  리소스 삭제를 시작합니다...")

        # 삭제 순서: 의존성 역순
        # 1) EventBridge Schedules (Lambda, Step Functions를 참조)
        schedules_count = cleanup_schedules(scheduler_src, scheduler_dst)

        # 2) EventBridge Schedule Groups
        schedule_groups_count = cleanup_schedule_groups(scheduler_src, scheduler_dst)

        # 3) EventBridge 규칙 (Lambda, Step Functions를 참조)
        eventbridge_count = cleanup_eventbridge_rules(events_src, events_dst)

        # 4) Step Functions (Lambda를 참조)
        sfn_count = cleanup_step_functions(sfn_src, sfn_dst)

        # 5) Lambda 함수 (Layer를 참조)
        lambda_count = cleanup_lambda_functions(lambda_src, lambda_dst)

        # 6) Lambda Layers
        layer_count = cleanup_lambda_layers(lambda_src, lambda_dst)

        logger.info("\n" + "="*70)
        logger.info("✅ 전체 리소스 정리 완료!")
        logger.info("="*70)
        logger.info(f"EventBridge Schedules: {schedules_count}개 삭제")
        logger.info(f"EventBridge Schedule Groups: {schedule_groups_count}개 삭제")
        logger.info(f"EventBridge Rules: {eventbridge_count}개 삭제")
        logger.info(f"Step Functions: {sfn_count}개 삭제")
        logger.info(f"Lambda Functions: {lambda_count}개 삭제")
        logger.info(f"Lambda Layers: {layer_count}개 삭제")
        logger.info("="*70)

    except Exception as e:
        logger.error(f"\n❌ 정리 중 치명적 오류 발생: {e}")
        raise


if __name__ == "__main__":
    main()
