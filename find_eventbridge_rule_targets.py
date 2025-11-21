#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import boto3
import json
import os

SRC_PROFILE = os.getenv("SRC_PROFILE", "src")
REGION = os.getenv("AWS_REGION", "ap-northeast-2")

src_sess = boto3.Session(profile_name=SRC_PROFILE, region_name=REGION)
events = src_sess.client('events')
sfn = src_sess.client('stepfunctions')

print("\n" + "="*70)
print("EventBridge Rules에서 Step Functions 타겟 검색")
print("="*70)

# 모든 상태 머신 ARN을 이름으로 매핑
sm_arn_to_name = {}
machines = sfn.list_state_machines()
for sm in machines.get('stateMachines', []):
    sm_arn_to_name[sm['stateMachineArn']] = sm['name']

# EventBridge Rule 확인
rules = events.list_rules()
for rule in rules.get('Rules', []):
    rule_name = rule['Name']

    # Step Functions 관련 Rule만 확인
    if 'StepFunctions' in rule_name or 'states' in rule.get('Description', '').lower():
        targets = events.list_targets_by_rule(Rule=rule_name)

        sfn_targets = []
        for target in targets.get('Targets', []):
            target_arn = target.get('Arn', '')
            if 'states' in target_arn or 'stepfunctions' in target_arn:
                # ARN에서 상태 머신 이름 찾기
                sm_name = sm_arn_to_name.get(target_arn, "Unknown")
                sfn_targets.append({
                    'arn': target_arn,
                    'name': sm_name,
                    'id': target.get('Id')
                })

        if sfn_targets:
            print(f"\n⚠️  Rule: {rule_name}")
            print(f"   State: {rule.get('State', 'N/A')}")
            if rule.get('ScheduleExpression'):
                print(f"   Schedule: {rule['ScheduleExpression']}")

            print(f"\n   Step Functions 타겟:")
            for target in sfn_targets:
                print(f"   - {target['name']}")
                print(f"     ARN: {target['arn']}")
                print(f"     Target ID: {target['id']}")
            print("\n" + "-"*70)

print("\n" + "="*70)
print("검색 완료!")
print("="*70)
print("\n💡 위에 표시된 상태 머신들이 EventBridge Rule과 연결되어 있습니다.")
print("   이 상태 머신들을 마이그레이션할 때 managed-rule 권한이 필요합니다.")
