# IAM Policy 샘플

이 디렉토리에는 AWS 리소스 마이그레이션에 필요한 IAM 정책 샘플이 포함되어 있습니다.

## 📋 정책 파일 목록

### 자동 적용되는 정책 (마이그레이션 스크립트가 자동 생성)

1. **EventBridge Rules 실행 Role**
   - Trust Policy: `eventbridge-rules-trust-policy.json`
   - 권한 Policy: `eventbridge-rules-role-policy.json`
   - Role 이름: `EventBridgeRulesExecutionRole`
   - 스크립트가 자동으로 생성하므로 수동 적용 불필요!

2. **EventBridge Scheduler 실행 Role**
   - Trust Policy: `eventbridge-scheduler-trust-policy.json`
   - 권한 Policy: `eventbridge-scheduler-role-policy.json`
   - Role 이름: `EventBridgeSchedulerExecutionRole`
   - 스크립트가 자동으로 생성하므로 수동 적용 불필요!

### 수동 적용이 필요한 정책

3. **Step Functions 실행 Role**
   - 권한 Policy: `stepfunctions-role-policy.json`
   - 마이그레이션 전에 수동으로 적용해야 함

---

## EventBridge Rules Role 정책 (자동 생성)

**파일**:
- Trust Policy: `eventbridge-rules-trust-policy.json`
- 권한 Policy: `eventbridge-rules-role-policy.json`

### 자동 생성 방식

마이그레이션 스크립트가 자동으로:
1. Role 존재 여부 확인
2. 없으면 Trust Policy로 Role 생성
3. 권한 Policy를 Inline Policy로 첨부
4. 모든 EventBridge Rules에 이 Role 자동 할당

### Trust Relationship

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "events.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

### 권한

- Lambda 함수 호출 (`lambda:InvokeFunction`)
- Step Functions 실행 (`states:StartExecution`)
- SQS 메시지 전송 (`sqs:SendMessage`)
- SNS 메시지 발행 (`sns:Publish`)
- EventBridge 이벤트 전송 (`events:PutEvents`)

---

## EventBridge Scheduler Role 정책 (자동 생성)

**파일**:
- Trust Policy: `eventbridge-scheduler-trust-policy.json`
- 권한 Policy: `eventbridge-scheduler-role-policy.json`

### 자동 생성 방식

마이그레이션 스크립트가 자동으로:
1. Role 존재 여부 확인
2. 없으면 Trust Policy로 Role 생성
3. 권한 Policy를 Inline Policy로 첨부
4. 모든 EventBridge Schedules에 이 Role 자동 할당

### Trust Relationship

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "scheduler.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

### 권한

- Lambda 함수 호출 (`lambda:InvokeFunction`)
- Step Functions 실행 (`states:StartExecution`)
- SQS 메시지 전송 (`sqs:SendMessage`)
- SNS 메시지 발행 (`sns:Publish`)
- EventBridge 이벤트 전송 (`events:PutEvents`)

---

## Step Functions Role 정책 (수동 적용 필요)

**파일**: `stepfunctions-role-policy.json`

### 사용 방법

#### AWS Console에서 적용

1. **IAM Console 이동**
   - AWS Console > IAM > Roles
   - Step Functions 실행 역할 선택 (예: `skies-dp-prd-dip-sfn-default-role`)

2. **Inline Policy 추가**
   - "Permissions" 탭 선택
   - "Add permissions" → "Create inline policy" 클릭
   - "JSON" 탭 선택
   - `stepfunctions-role-policy.json` 파일 내용 붙여넣기
   - "Review policy" 클릭
   - Policy name 입력 (예: `StepFunctionsExecutionPolicy`)
   - "Create policy" 클릭

#### AWS CLI로 적용

```bash
# IAM Role에 Inline Policy 추가
aws iam put-role-policy \
  --role-name skies-dp-prd-dip-sfn-default-role \
  --policy-name StepFunctionsExecutionPolicy \
  --policy-document file://iam-policies/stepfunctions-role-policy.json
```

#### Terraform으로 적용

```hcl
resource "aws_iam_role_policy" "stepfunctions_execution" {
  name = "StepFunctionsExecutionPolicy"
  role = aws_iam_role.stepfunctions.id

  policy = file("${path.module}/iam-policies/stepfunctions-role-policy.json")
}
```

### 정책 설명

이 정책은 Step Functions가 다음 작업을 수행할 수 있도록 허용합니다:

1. **StepFunctionsExecution** (`states:*`)
   - Step Functions 상태 머신 실행 및 관리

2. **EventBridgeManagedRules** (`events:*` + Condition) ⚠️ **중요!**
   - Step Functions가 EventBridge와 통합될 때 자동으로 managed rule 생성
   - **`Condition`이 없으면 `"is not authorized to create managed-rule"` 오류 발생**
   - `"events:ManagedBy": "states.amazonaws.com"` 조건이 반드시 필요

3. **LambdaInvocation** (`lambda:InvokeFunction`)
   - Step Functions에서 Lambda 함수 호출

4. **CloudWatchLogs** (`logs:*`)
   - Step Functions 실행 로그 기록

5. **XRayTracing** (`xray:*`)
   - Step Functions 추적 및 디버깅

### 주의사항

- ⚠️ **EventBridge 권한에 `Condition` 블록이 반드시 포함되어야 합니다!**
- `Condition`이 없으면 Step Functions가 managed rule을 생성할 수 없습니다.
- 이는 Step Functions가 EventBridge 스케줄러나 규칙과 통합될 때 필요합니다.

### 오류 해결

만약 다음과 같은 오류가 발생한다면:

```
AccessDeniedException: 'arn:aws:iam::ACCOUNT:role/ROLE_NAME' is not authorized to create managed-rule
```

**원인**: EventBridge 권한에 `Condition`이 누락되었습니다.

**해결**: 위 정책 파일을 그대로 적용하거나, 기존 정책에서 EventBridge Statement를 확인하여 `Condition` 블록을 추가하세요.

### 확인 방법

정책이 올바르게 적용되었는지 확인:

```bash
# IAM Role 정책 확인
aws iam get-role-policy \
  --role-name skies-dp-prd-dip-sfn-default-role \
  --policy-name StepFunctionsExecutionPolicy
```

출력에서 다음을 확인:
1. `events:PutRule`, `events:PutTargets` 등의 권한이 있는지
2. `Condition` 블록이 있고 `"events:ManagedBy": "states.amazonaws.com"`가 포함되어 있는지

## 참고 자료

- [AWS Step Functions IAM Policies](https://docs.aws.amazon.com/step-functions/latest/dg/procedure-create-iam-role.html)
- [EventBridge Managed Rules](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-rules.html)
