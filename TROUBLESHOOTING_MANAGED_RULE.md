# Step Functions "managed-rule" 오류 상세 트러블슈팅

## 오류 메시지
```
AccessDeniedException: 'arn:aws:iam::ACCOUNT:role/ROLE_NAME' is not authorized to create managed-rule
```

## 단계별 확인 사항

### 1. IAM Role Trust Relationship 확인 ⭐ 중요

Step Functions 서비스가 해당 Role을 assume할 수 있어야 합니다.

#### 확인 방법 (AWS Console):
1. IAM > Roles > `skies-dp-prd-dip-sfn-default-role`
2. **Trust relationships** 탭 선택
3. 다음과 같은 내용이 있어야 함:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "states.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

#### 확인 방법 (AWS CLI):
```bash
aws iam get-role --role-name skies-dp-prd-dip-sfn-default-role --query 'Role.AssumeRolePolicyDocument'
```

**만약 `states.amazonaws.com`이 없다면 추가해야 합니다!**

---

### 2. EventBridge 권한의 Resource 범위 확인

EventBridge 권한의 `Resource`가 `"*"`로 설정되어 있는지 확인하세요.

#### 잘못된 예 (특정 ARN으로 제한):
```json
{
  "Effect": "Allow",
  "Action": ["events:PutRule", ...],
  "Resource": "arn:aws:events:ap-northeast-2:846697434179:rule/specific-rule",  // ❌ 이렇게 하면 안됨
  "Condition": { ... }
}
```

#### 올바른 예:
```json
{
  "Effect": "Allow",
  "Action": ["events:PutRule", ...],
  "Resource": "*",  // ✅ 모든 리소스 허용
  "Condition": {
    "StringEquals": {
      "events:ManagedBy": "states.amazonaws.com"
    }
  }
}
```

---

### 3. 명시적 Deny 정책 확인

다른 정책에서 EventBridge 권한을 명시적으로 거부하고 있는지 확인하세요.

#### 확인 방법:
```bash
# Role에 연결된 모든 정책 확인
aws iam list-attached-role-policies --role-name skies-dp-prd-dip-sfn-default-role

# 각 정책의 내용 확인
aws iam get-policy-version \
  --policy-arn arn:aws:iam::ACCOUNT:policy/POLICY_NAME \
  --version-id v1
```

**다음과 같은 Deny 문이 있는지 확인:**
```json
{
  "Effect": "Deny",
  "Action": "events:*",
  ...
}
```

---

### 4. IAM 정책 전파 대기

IAM 정책을 추가하거나 수정한 직후라면, AWS가 정책을 전파하는 데 시간이 걸릴 수 있습니다.

**해결 방법:**
- 정책 추가 후 **5-10분 정도 대기**
- 그 다음 마이그레이션 스크립트 재실행

---

### 5. 실제 사용되는 Role ARN 확인

스크립트가 실제로 올바른 Role을 사용하고 있는지 확인하세요.

#### 확인 방법:
```bash
# 환경 변수 확인
echo $DEFAULT_DEST_SFN_ROLE

# 출력이 다음과 같아야 함:
# arn:aws:iam::846697434179:role/skies-dp-prd-dip-sfn-default-role
```

만약 다른 Role을 사용한다면 해당 Role에도 동일한 권한이 필요합니다.

---

### 6. 기존 Managed Rule 충돌 확인

같은 이름의 managed rule이 이미 존재할 수 있습니다.

#### 확인 방법:
```bash
# EventBridge Rules 목록 확인
aws events list-rules --name-prefix "StatesExecution"

# 특정 rule이 있다면 삭제 (주의!)
aws events delete-rule --name RULE_NAME
```

**주의:** 이미 사용 중인 rule을 삭제하면 안 됩니다!

---

### 7. State Machine 정의 확인

상태 머신 정의에서 EventBridge 통합이 어떻게 구성되어 있는지 확인하세요.

#### 소스 계정에서 정의 추출:
```bash
# Python으로 확인
python3 << 'EOF'
import boto3
import json

src = boto3.Session(profile_name='src', region_name='ap-northeast-2')
sfn = src.client('stepfunctions')

machines = sfn.list_state_machines()
for sm in machines.get('stateMachines', []):
    if 'weatherdata' in sm['name']:
        detail = sfn.describe_state_machine(stateMachineArn=sm['stateMachineArn'])
        print(f"\n=== {sm['name']} ===")
        print(json.dumps(json.loads(detail['definition']), indent=2))
EOF
```

특히 다음과 같은 패턴을 찾아보세요:
- `"Type": "Task"` with `"Resource": "arn:aws:states:::events:putEvents"`
- EventBridge 통합 관련 설정

---

### 8. SCP (Service Control Policy) 확인 (Organizations 사용 시)

AWS Organizations를 사용한다면 SCP가 권한을 제한하고 있을 수 있습니다.

#### 확인 방법:
```bash
# 계정의 SCP 목록 확인
aws organizations list-policies-for-target \
  --target-id ACCOUNT_ID \
  --filter SERVICE_CONTROL_POLICY
```

SCP에서 EventBridge 권한을 제한하고 있다면 조직 관리자에게 요청해야 합니다.

---

## 종합 체크리스트

다음을 순서대로 확인하세요:

- [ ] Trust Relationship에 `states.amazonaws.com` 포함 여부
- [ ] EventBridge 권한의 Resource가 `"*"`인지 확인
- [ ] EventBridge 권한에 Condition 블록 포함 확인
- [ ] 명시적 Deny 정책이 없는지 확인
- [ ] IAM 정책 추가 후 5-10분 대기했는지
- [ ] 환경 변수 `DEFAULT_DEST_SFN_ROLE`이 올바른지 확인
- [ ] 기존 managed rule 충돌 확인
- [ ] SCP 제한 확인 (해당되는 경우)

---

## 빠른 해결 스크립트

다음 스크립트로 주요 항목을 자동 확인할 수 있습니다:

```bash
#!/bin/bash

ROLE_NAME="skies-dp-prd-dip-sfn-default-role"

echo "=== 1. Trust Relationship 확인 ==="
aws iam get-role --role-name $ROLE_NAME --query 'Role.AssumeRolePolicyDocument' --output json

echo -e "\n=== 2. 연결된 정책 목록 ==="
aws iam list-attached-role-policies --role-name $ROLE_NAME

echo -e "\n=== 3. Inline 정책 목록 ==="
aws iam list-role-policies --role-name $ROLE_NAME

echo -e "\n=== 4. Inline 정책 내용 확인 ==="
for policy in $(aws iam list-role-policies --role-name $ROLE_NAME --query 'PolicyNames' --output text); do
  echo "--- Policy: $policy ---"
  aws iam get-role-policy --role-name $ROLE_NAME --policy-name $policy --output json
done

echo -e "\n=== 5. EventBridge Rules 확인 ==="
aws events list-rules --name-prefix "StatesExecution" --max-items 10
```

저장 후 실행:
```bash
chmod +x check_iam_role.sh
./check_iam_role.sh
```

---

## 여전히 해결되지 않는다면

위 모든 항목을 확인했는데도 여전히 오류가 발생한다면:

1. **AWS Support에 문의**
   - 케이스 설명: "Step Functions CreateStateMachine managed-rule AccessDeniedException"
   - Role ARN, 정책 내용, 오류 메시지 첨부

2. **대안: EventBridge 통합 제거**
   - 상태 머신 정의에서 EventBridge 통합 부분을 임시로 제거
   - 수동으로 EventBridge Rule 생성
   - 단, 이는 임시 해결책입니다

3. **CloudTrail 로그 확인**
   ```bash
   aws cloudtrail lookup-events \
     --lookup-attributes AttributeKey=EventName,AttributeValue=CreateStateMachine \
     --max-items 10
   ```
   실제 거부 이유가 CloudTrail에 더 상세히 기록되어 있을 수 있습니다.
