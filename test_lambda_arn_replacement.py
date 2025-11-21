#!/usr/bin/env python3
"""
Lambda ARN 교체 로직 테스트
"""
import json

# 테스트용 LAMBDA_ARN_MAP 시뮬레이션
LAMBDA_ARN_MAP = {
    "arn:aws:lambda:us-east-1:111111111111:function:my-function": "arn:aws:lambda:us-east-1:222222222222:function:my-function",
    "arn:aws:lambda:us-east-1:111111111111:function:another-function": "arn:aws:lambda:us-east-1:222222222222:function:another-function"
}

def replace_lambda_arns_in_definition(definition: dict, src_account: str, dst_account: str) -> dict:
    """
    StepFunction 정의에서 Lambda ARN을 재귀적으로 교체
    버전/alias가 포함된 Lambda ARN도 올바르게 처리
    Resource 필드뿐만 아니라 FunctionName 필드도 확인 (Parameters.FunctionName 등)
    """
    if isinstance(definition, dict):
        new_dict = {}
        for key, value in definition.items():
            # Lambda ARN이 포함될 수 있는 필드들: Resource, FunctionName
            if key in ("Resource", "FunctionName") and isinstance(value, str):
                # Lambda ARN 교체
                if "arn:aws:lambda" in value and src_account in value:
                    # Lambda ARN에서 버전/alias 분리
                    # 형식: arn:aws:lambda:region:account:function:function-name[:version-or-alias]
                    base_arn = value
                    version_or_alias = None

                    # 버전이나 alias 확인 (마지막 콜론 이후)
                    arn_parts = value.split(":")
                    if len(arn_parts) >= 8:  # 버전/alias가 포함된 경우
                        version_or_alias = arn_parts[7]
                        base_arn = ":".join(arn_parts[:7])  # 기본 ARN (버전/alias 제외)

                    # LAMBDA_ARN_MAP에서 기본 ARN으로 찾기
                    mapped = LAMBDA_ARN_MAP.get(base_arn)
                    if mapped:
                        # 매핑을 찾으면 버전/alias 유지하면서 교체
                        if version_or_alias:
                            new_arn = f"{mapped}:{version_or_alias}"
                        else:
                            new_arn = mapped
                        new_dict[key] = new_arn
                        print(f"  ✓ Replaced Lambda ARN in '{key}': {value} -> {new_arn}")
                    else:
                        # 매핑이 없으면 계정 ID만 교체
                        new_dict[key] = value.replace(src_account, dst_account)
                        print(f"  ⚠ No mapping found for base ARN '{base_arn}' in '{key}', replaced account ID: {value} -> {new_dict[key]}")
                else:
                    new_dict[key] = value
            else:
                new_dict[key] = replace_lambda_arns_in_definition(value, src_account, dst_account)
        return new_dict
    elif isinstance(definition, list):
        return [replace_lambda_arns_in_definition(item, src_account, dst_account) for item in definition]
    else:
        return definition

# 테스트 케이스
print("="*70)
print("Lambda ARN 교체 로직 테스트")
print("="*70)

src_account = "111111111111"
dst_account = "222222222222"

# 테스트 1: 버전 없는 기본 ARN
print("\n[Test 1] 버전 없는 기본 ARN")
test1 = {
    "Resource": "arn:aws:lambda:us-east-1:111111111111:function:my-function"
}
result1 = replace_lambda_arns_in_definition(test1, src_account, dst_account)
print(f"Input:  {test1['Resource']}")
print(f"Output: {result1['Resource']}")
print(f"Expected: arn:aws:lambda:us-east-1:222222222222:function:my-function")
print(f"Pass: {result1['Resource'] == 'arn:aws:lambda:us-east-1:222222222222:function:my-function'}")

# 테스트 2: $LATEST 버전이 있는 ARN
print("\n[Test 2] $LATEST 버전이 있는 ARN")
test2 = {
    "Resource": "arn:aws:lambda:us-east-1:111111111111:function:my-function:$LATEST"
}
result2 = replace_lambda_arns_in_definition(test2, src_account, dst_account)
print(f"Input:  {test2['Resource']}")
print(f"Output: {result2['Resource']}")
print(f"Expected: arn:aws:lambda:us-east-1:222222222222:function:my-function:$LATEST")
print(f"Pass: {result2['Resource'] == 'arn:aws:lambda:us-east-1:222222222222:function:my-function:$LATEST'}")

# 테스트 3: 숫자 버전이 있는 ARN
print("\n[Test 3] 숫자 버전이 있는 ARN")
test3 = {
    "Resource": "arn:aws:lambda:us-east-1:111111111111:function:my-function:1"
}
result3 = replace_lambda_arns_in_definition(test3, src_account, dst_account)
print(f"Input:  {test3['Resource']}")
print(f"Output: {result3['Resource']}")
print(f"Expected: arn:aws:lambda:us-east-1:222222222222:function:my-function:1")
print(f"Pass: {result3['Resource'] == 'arn:aws:lambda:us-east-1:222222222222:function:my-function:1'}")

# 테스트 4: Alias가 있는 ARN
print("\n[Test 4] Alias가 있는 ARN")
test4 = {
    "Resource": "arn:aws:lambda:us-east-1:111111111111:function:my-function:prod"
}
result4 = replace_lambda_arns_in_definition(test4, src_account, dst_account)
print(f"Input:  {test4['Resource']}")
print(f"Output: {result4['Resource']}")
print(f"Expected: arn:aws:lambda:us-east-1:222222222222:function:my-function:prod")
print(f"Pass: {result4['Resource'] == 'arn:aws:lambda:us-east-1:222222222222:function:my-function:prod'}")

# 테스트 5: 매핑에 없는 Lambda 함수 (fallback to account ID replacement)
print("\n[Test 5] 매핑에 없는 Lambda 함수")
test5 = {
    "Resource": "arn:aws:lambda:us-east-1:111111111111:function:unknown-function"
}
result5 = replace_lambda_arns_in_definition(test5, src_account, dst_account)
print(f"Input:  {test5['Resource']}")
print(f"Output: {result5['Resource']}")
print(f"Expected: arn:aws:lambda:us-east-1:222222222222:function:unknown-function")
print(f"Pass: {result5['Resource'] == 'arn:aws:lambda:us-east-1:222222222222:function:unknown-function'}")

# 테스트 6: 중첩된 상태머신 정의
print("\n[Test 6] 중첩된 상태머신 정의")
test6 = {
    "States": {
        "Task1": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:us-east-1:111111111111:function:my-function:$LATEST",
            "Next": "Task2"
        },
        "Task2": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:us-east-1:111111111111:function:another-function:1",
            "End": True
        }
    }
}
result6 = replace_lambda_arns_in_definition(test6, src_account, dst_account)
print(f"Input Task1:  {test6['States']['Task1']['Resource']}")
print(f"Output Task1: {result6['States']['Task1']['Resource']}")
print(f"Input Task2:  {test6['States']['Task2']['Resource']}")
print(f"Output Task2: {result6['States']['Task2']['Resource']}")
print(f"Pass: {result6['States']['Task1']['Resource'] == 'arn:aws:lambda:us-east-1:222222222222:function:my-function:$LATEST' and result6['States']['Task2']['Resource'] == 'arn:aws:lambda:us-east-1:222222222222:function:another-function:1'}")

# 테스트 7: Parameters.FunctionName 필드 (lambda:invoke 패턴)
print("\n[Test 7] Parameters.FunctionName 필드 (lambda:invoke 패턴)")
test7 = {
    "Type": "Task",
    "Resource": "arn:aws:states:::lambda:invoke",
    "Parameters": {
        "FunctionName": "arn:aws:lambda:us-east-1:111111111111:function:my-function"
    }
}
result7 = replace_lambda_arns_in_definition(test7, src_account, dst_account)
print(f"Input Resource:  {test7['Resource']}")
print(f"Output Resource: {result7['Resource']}")
print(f"Input FunctionName:  {test7['Parameters']['FunctionName']}")
print(f"Output FunctionName: {result7['Parameters']['FunctionName']}")
print(f"Expected Resource: arn:aws:states:::lambda:invoke (unchanged)")
print(f"Expected FunctionName: arn:aws:lambda:us-east-1:222222222222:function:my-function")
print(f"Pass: {result7['Resource'] == 'arn:aws:states:::lambda:invoke' and result7['Parameters']['FunctionName'] == 'arn:aws:lambda:us-east-1:222222222222:function:my-function'}")

# 테스트 8: Parameters.FunctionName with version (lambda:invoke 패턴)
print("\n[Test 8] Parameters.FunctionName with $LATEST (lambda:invoke 패턴)")
test8 = {
    "Type": "Task",
    "Resource": "arn:aws:states:::lambda:invoke",
    "Parameters": {
        "Payload": {
            "key": "value"
        },
        "FunctionName": "arn:aws:lambda:us-east-1:111111111111:function:my-function:$LATEST"
    }
}
result8 = replace_lambda_arns_in_definition(test8, src_account, dst_account)
print(f"Input FunctionName:  {test8['Parameters']['FunctionName']}")
print(f"Output FunctionName: {result8['Parameters']['FunctionName']}")
print(f"Expected: arn:aws:lambda:us-east-1:222222222222:function:my-function:$LATEST")
print(f"Pass: {result8['Parameters']['FunctionName'] == 'arn:aws:lambda:us-east-1:222222222222:function:my-function:$LATEST'}")

# 테스트 9: 실제 상태머신 정의 (사용자가 보여준 패턴)
print("\n[Test 9] 실제 상태머신 정의 (Parameters.FunctionName with Payload)")
LAMBDA_ARN_MAP["arn:aws:lambda:ap-northeast-2:507124486027:function:model_reprocessing"] = "arn:aws:lambda:ap-northeast-2:999999999999:function:model_reprocessing"
test9 = {
    "StartAt": "재처리 정보 입력",
    "States": {
        "재처리 날짜 입력 생성": {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "OutputPath": "$.Payload",
            "Parameters": {
                "Payload.$": "$",
                "FunctionName": "arn:aws:lambda:ap-northeast-2:507124486027:function:model_reprocessing"
            },
            "Next": "재처리 날짜 결과 생성"
        }
    }
}
result9 = replace_lambda_arns_in_definition(test9, "507124486027", "999999999999")
print(f"Input FunctionName:  {test9['States']['재처리 날짜 입력 생성']['Parameters']['FunctionName']}")
print(f"Output FunctionName: {result9['States']['재처리 날짜 입력 생성']['Parameters']['FunctionName']}")
print(f"Expected: arn:aws:lambda:ap-northeast-2:999999999999:function:model_reprocessing")
print(f"Pass: {result9['States']['재처리 날짜 입력 생성']['Parameters']['FunctionName'] == 'arn:aws:lambda:ap-northeast-2:999999999999:function:model_reprocessing'}")

print("\n" + "="*70)
print("테스트 완료")
print("="*70)
