#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import boto3
import json
import os

SRC_PROFILE = os.getenv("SRC_PROFILE", "src")
REGION = os.getenv("AWS_REGION", "ap-northeast-2")

src_sess = boto3.Session(profile_name=SRC_PROFILE, region_name=REGION)
sfn_src = src_sess.client("stepfunctions")

print("\n" + "="*70)
print("Step Functions 정의에서 EventBridge 통합 검색")
print("="*70)

machines = sfn_src.list_state_machines()

for sm in machines.get("stateMachines", []):
    sm_name = sm["name"]
    sm_arn = sm["stateMachineArn"]

    detail = sfn_src.describe_state_machine(stateMachineArn=sm_arn)
    definition = json.loads(detail["definition"])
    definition_str = json.dumps(definition)

    # EventBridge 통합 패턴 검색
    has_eventbridge = False
    eventbridge_patterns = []

    if "arn:aws:states:::events:" in definition_str:
        has_eventbridge = True
        eventbridge_patterns.append("states:::events: (EventBridge 통합)")

    if "arn:aws:states:::aws-sdk:eventbridge:" in definition_str:
        has_eventbridge = True
        eventbridge_patterns.append("aws-sdk:eventbridge: (AWS SDK EventBridge)")

    if "arn:aws:states:::scheduler:" in definition_str:
        has_eventbridge = True
        eventbridge_patterns.append("states:::scheduler: (EventBridge Scheduler)")

    if '"eventbridge"' in definition_str.lower():
        has_eventbridge = True
        eventbridge_patterns.append("eventbridge 키워드 발견")

    if has_eventbridge:
        print(f"\n⚠️  {sm_name}")
        print(f"   ARN: {sm_arn}")
        print(f"   EventBridge 통합 발견:")
        for pattern in eventbridge_patterns:
            print(f"   - {pattern}")
        print(f"\n   상태 머신 정의:")
        print(json.dumps(definition, indent=2, ensure_ascii=False))
        print("\n" + "-"*70)
    else:
        print(f"✅ {sm_name} - EventBridge 통합 없음")

print("\n" + "="*70)
print("검색 완료!")
print("="*70)
