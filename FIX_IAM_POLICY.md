# Step Functions EventBridge 권한 정책 수정 가이드

## 🚨 문제 발견

현재 IAM 정책의 Condition이 잘못되어 있습니다:

```json
❌ 잘못된 정책:
{
  "Effect": "Allow",
  "Action": [
    "events:PutRule",
    "events:PutTargets",
    "events:DescribeRule",
    "events:DeleteRule",
    "events:RemoveTargets"
  ],
  "Resource": "*",
  "Condition": {
    "StringEquals": {
      "events:ManagedBy": "states.amazonaws.com"
    }
  }
}
```

**문제**: `events:ManagedBy`는 **이미 생성된 Rule의 속성**입니다.
새로운 Rule을 생성할 때는 아직 이 속성이 없기 때문에 Condition이 실패합니다!

---

## ✅ 올바른 정책 (3가지 옵션)

### 옵션 1: Rule 이름 패턴으로 제한 (권장)

Step Functions가 생성하는 managed rule은 특정 naming pattern을 따릅니다:
- `StepFunctionsGetEventsForStepFunctionsExecutionRule`
- `StepFunctions-*`

```json
{
  "Effect": "Allow",
  "Action": [
    "events:PutRule",
    "events:PutTargets",
    "events:DescribeRule"
  ],
  "Resource": "arn:aws:events:*:846697434179:rule/StepFunctions*"
}
```

```json
{
  "Effect": "Allow",
  "Action": [
    "events:DeleteRule",
    "events:RemoveTargets"
  ],
  "Resource": "arn:aws:events:*:846697434179:rule/StepFunctions*",
  "Condition": {
    "StringEquals": {
      "events:ManagedBy": "states.amazonaws.com"
    }
  }
}
```

**설명**:
- Rule 생성/업데이트는 이름 패턴으로 제한
- Rule 삭제는 ManagedBy 속성 확인 (이미 생성된 Rule이므로 가능)

---

### 옵션 2: Condition 완전 제거 (간단하지만 덜 안전)

```json
{
  "Effect": "Allow",
  "Action": [
    "events:PutRule",
    "events:PutTargets",
    "events:DescribeRule",
    "events:DeleteRule",
    "events:RemoveTargets"
  ],
  "Resource": "*"
}
```

**장점**: 간단하고 즉시 작동
**단점**: 보안이 약함 (모든 EventBridge Rule에 대한 권한)

---

### 옵션 3: 소스 기반 Condition (AWS 권장)

```json
{
  "Effect": "Allow",
  "Action": [
    "events:PutRule",
    "events:PutTargets",
    "events:DescribeRule",
    "events:DeleteRule",
    "events:RemoveTargets"
  ],
  "Resource": "*",
  "Condition": {
    "StringEquals": {
      "aws:SourceAccount": "846697434179"
    },
    "ArnLike": {
      "aws:SourceArn": "arn:aws:states:ap-northeast-2:846697434179:*"
    }
  }
}
```

**설명**: Step Functions에서 호출하는 경우만 허용

---

## 🔧 즉시 적용 방법

### AWS Console에서:

1. **IAM** → **Roles** → `skies-dp-prd-dip-sfn-default-role`
2. **Permissions** 탭에서 EventBridge 정책 찾기
3. **Edit policy** 클릭
4. 기존 Statement를 **옵션 1** 또는 **옵션 2**로 교체
5. **Review policy** → **Save changes**

### AWS CLI로:

```bash
# 현재 정책 백업
aws iam get-role-policy \
  --role-name skies-dp-prd-dip-sfn-default-role \
  --policy-name <정책이름> \
  --profile dst > backup_policy.json

# 새 정책 적용 (옵션 2 - 가장 간단)
cat > new_policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "events:PutRule",
        "events:PutTargets",
        "events:DescribeRule",
        "events:DeleteRule",
        "events:RemoveTargets"
      ],
      "Resource": "*"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name skies-dp-prd-dip-sfn-default-role \
  --policy-name EventBridgeManagedRules \
  --policy-document file://new_policy.json \
  --profile dst
```

---

## 📋 권장 사항

**프로덕션 환경**: 옵션 1 사용 (가장 안전)
**테스트/개발 환경**: 옵션 2 사용 (가장 간단)

---

## ⏱️ 적용 후

1. 정책 변경 후 **5-10분 대기** (IAM 전파 시간)
2. 마이그레이션 스크립트 재실행:
   ```bash
   python migrate_aws_resources.py
   ```

---

## 🔍 확인 방법

정책 적용 후 확인:

```bash
aws iam get-role-policy \
  --role-name skies-dp-prd-dip-sfn-default-role \
  --policy-name EventBridgeManagedRules \
  --profile dst
```

Condition 블록이 제거되었거나 올바른 형태로 변경되었는지 확인하세요.

---

## 📚 참고 자료

- [AWS Step Functions IAM Policies](https://docs.aws.amazon.com/step-functions/latest/dg/procedure-create-iam-role.html)
- [EventBridge Resource-based Policies](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-use-resource-based.html)
- [IAM Policy Condition Keys](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_condition-keys.html)
