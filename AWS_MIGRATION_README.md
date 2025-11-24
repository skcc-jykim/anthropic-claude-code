# AWS 리소스 마이그레이션 도구

AWS 계정 간 Lambda, Step Functions, EventBridge 규칙 및 EventBridge Scheduler를 자동으로 마이그레이션하는 Python 스크립트입니다.

## 🎉 주요 기능 (NEW: EventBridge 실행 Role 자동 생성!)

**이 스크립트는 EventBridge Rules 및 Scheduler가 Lambda/StepFunctions를 호출하는데 필요한 IAM Role을 자동으로 생성합니다!**

더 이상 수동으로 IAM Role을 생성하거나 Trust Relationship을 설정할 필요가 없습니다.

### ✅ 마이그레이션 대상 리소스

0. **IAM Roles (자동 생성)**
   - **EventBridge Rules 실행 Role** (자동 생성)
     - Trust Relationship: `events.amazonaws.com`
     - 권한: Lambda 호출, Step Functions 실행, SQS/SNS 발행 등
   - **EventBridge Scheduler 실행 Role** (자동 생성)
     - Trust Relationship: `scheduler.amazonaws.com`
     - 권한: Lambda 호출, Step Functions 실행, SQS/SNS 발행 등
   - 기존 Role이 있으면 재사용, 없으면 자동 생성

1. **Lambda Layers**
   - 자동으로 모든 Layer 버전 감지 및 복제
   - Layer ARN 자동 매핑

2. **Lambda Functions**
   - 함수 코드 및 설정
   - 환경 변수
   - VPC 설정 (서브넷, 보안 그룹)
   - IAM Role 매핑
   - Layer 연결
   - 태그
   - 예약 동시성 설정
   - Dead Letter Queue (DLQ)

3. **Step Functions**
   - 상태 머신 정의
   - Lambda ARN 자동 교체
   - IAM Role 매핑
   - Logging 및 Tracing 설정
   - 태그

4. **EventBridge 규칙**
   - 스케줄 표현식 (Cron/Rate)
   - 이벤트 패턴
   - 타겟 설정 (Lambda, Step Functions, SQS, SNS 등)
   - 재시도 정책
   - DLQ 설정
   - 태그

5. **EventBridge Scheduler (신규 추가)**
   - Schedule Groups
     - 그룹 이름 및 설명
     - 태그
   - Schedules
     - 스케줄 표현식 (at, rate, cron)
     - Flexible Time Window
     - 타임존 설정
     - 시작/종료 날짜
     - 타겟 설정 (Lambda, Step Functions, SQS, SNS, EventBridge 등)
     - Lambda/Step Functions ARN 자동 매핑
     - Retry Policy
     - DLQ 설정
     - 태그

### 🔧 개선 사항 (기존 코드 대비)

1. **IAM Role 자동 생성 (NEW!)**
   - EventBridge Rules 및 Scheduler 실행 Role 자동 생성
   - Trust Relationship 자동 설정 (events.amazonaws.com, scheduler.amazonaws.com)
   - 필요한 권한 정책 자동 첨부 (Lambda, Step Functions, SQS, SNS 등)
   - 기존 Role이 있으면 재사용, 없으면 생성
   - 더 이상 수동으로 IAM 설정 필요 없음!

2. **로깅 시스템**
   - `print` 대신 `logging` 모듈 사용
   - 타임스탬프 및 로그 레벨 포함

3. **에러 처리**
   - API Throttling 자동 재시도 (지수 백오프)
   - 상세한 에러 메시지
   - 개별 리소스 실패 시에도 전체 프로세스 계속 진행

3. **ARN 매핑**
   - Lambda ARN 자동 매핑 및 추적
   - Step Functions 정의 내 Lambda ARN 자동 교체
   - EventBridge 타겟 ARN 자동 업데이트

4. **추가 설정 복제**
   - 태그 복제
   - 예약 동시성
   - DLQ 설정

## 사용 방법

### 1. 사전 요구사항

```bash
pip install boto3 requests
```

### 2. AWS 프로파일 설정

`~/.aws/credentials` 또는 `~/.aws/config`에 소스/대상 계정 프로파일 설정:

```ini
[src]
aws_access_key_id = YOUR_SRC_ACCESS_KEY
aws_secret_access_key = YOUR_SRC_SECRET_KEY

[dst]
aws_access_key_id = YOUR_DST_ACCESS_KEY
aws_secret_access_key = YOUR_DST_SECRET_KEY
```

### 3. 환경 변수 설정

```bash
# 필수
export SRC_PROFILE="src"
export DST_PROFILE="dst"
export AWS_REGION="ap-northeast-2"

# 선택 (특정 이름 접두사만 마이그레이션)
export NAME_PREFIX="my-service-"

# IAM Role 설정
export DEFAULT_DEST_LAMBDA_ROLE="arn:aws:iam::TARGET_ACCOUNT:role/lambda-execution-role"
export DEFAULT_DEST_SFN_ROLE="arn:aws:iam::TARGET_ACCOUNT:role/stepfunctions-execution-role"
```

### 4. 스크립트 수정

`migrate_aws_resources.py` 파일에서 매핑 설정 수정:

```python
# 서브넷 매핑
SUBNET_MAP = {
    "subnet-SOURCE-ID-1": "subnet-TARGET-ID-1",
    "subnet-SOURCE-ID-2": "subnet-TARGET-ID-2"
}

# 보안 그룹 매핑
SG_MAP = {
    "sg-SOURCE-ID": "sg-TARGET-ID",
}

# IAM Role 매핑 (선택적)
ROLE_MAP = {
    "arn:aws:iam::SRC_ACCOUNT:role/specific-role": "arn:aws:iam::DST_ACCOUNT:role/target-role"
}
```

### 5. 실행

```bash
python migrate_aws_resources.py
```

## 마이그레이션 순서

스크립트는 다음 순서로 리소스를 마이그레이션합니다:

0. **IAM Roles (NEW!)** - EventBridge Rules 및 Scheduler 실행 Role 자동 생성
1. **Lambda Layers** - Lambda가 의존하는 Layer를 먼저 복제
2. **Lambda Functions** - 함수 코드 및 설정 복제
3. **Step Functions** - 상태 머신 정의 복제 (Lambda ARN 자동 업데이트)
4. **EventBridge Rules** - 이벤트 규칙 및 타겟 복제 (자동 생성된 Role 사용)
5. **EventBridge Schedule Groups** - 일정 그룹 복제
6. **EventBridge Schedules** - 일정 복제 (Lambda/Step Functions ARN 자동 업데이트, 자동 생성된 Role 사용)

## 주의사항

### ⚠️ 사전 확인 필요

1. **IAM 권한**
   - 소스 계정: Lambda, Step Functions, EventBridge, EventBridge Scheduler 읽기 권한
   - 대상 계정:
     - Lambda, Step Functions, EventBridge, EventBridge Scheduler의 생성/수정 권한
     - **IAM Role 생성 및 정책 첨부 권한** (iam:CreateRole, iam:PutRolePolicy, iam:GetRole 등)

2. **네트워크 리소스**
   - VPC, 서브넷, 보안 그룹이 대상 계정에 미리 생성되어 있어야 함
   - `SUBNET_MAP`, `SG_MAP`에 정확한 매핑 설정 필요

3. **IAM Role**
   - **EventBridge Rules/Scheduler 실행 Role**: 스크립트가 자동으로 생성하므로 수동 설정 불필요!
   - Lambda 실행 Role: 대상 계정에 준비되어야 함
     - `DEFAULT_DEST_LAMBDA_ROLE` 환경 변수 설정
   - Step Functions 실행 Role: 대상 계정에 준비되어야 함
     - `DEFAULT_DEST_SFN_ROLE` 환경 변수 설정

   **Step Functions Role 필수 권한:**
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "states:*"
         ],
         "Resource": "*"
       },
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
       },
       {
         "Effect": "Allow",
         "Action": [
           "lambda:InvokeFunction"
         ],
         "Resource": "*"
       }
     ]
   }
   ```

   **⚠️ 중요**:
   - EventBridge 권한에 **반드시 `Condition`이 포함**되어야 합니다!
   - `Condition`이 없으면 `"is not authorized to create managed-rule"` 오류가 발생합니다.
   - Step Functions는 EventBridge 통합 시 자동으로 managed rule을 생성하며, 이는 `"events:ManagedBy": "states.amazonaws.com"` 조건이 필요합니다.

4. **DLQ 리소스**
   - Dead Letter Queue (SQS, SNS)가 대상 계정에 존재해야 함
   - 계정 ID만 자동 교체되므로, 동일한 이름의 리소스가 있어야 함

### ⚠️ 지원하지 않는 기능

1. **Container Image Lambda**
   - `PackageType: Image`인 Lambda는 자동으로 스킵됨
   - ECR 이미지를 별도로 마이그레이션해야 함

2. **커스텀 EventBridge 버스**
   - 현재는 `default` 이벤트 버스의 규칙만 마이그레이션
   - 커스텀 버스는 코드 수정 필요

3. **Lambda@Edge**
   - CloudFront Lambda@Edge는 지원 안 함

4. **암호화 키 (KMS)**
   - 환경 변수 암호화에 사용된 KMS 키는 자동으로 매핑되지 않음
   - 별도로 KMS 키 설정 필요

## 트러블슈팅

### 1. Throttling 에러

```
TooManyRequestsException: Rate exceeded
```

**해결**: 스크립트가 자동으로 재시도하지만, `MAX_RETRIES`와 `RETRY_DELAY`를 조정할 수 있습니다.

```python
MAX_RETRIES = 5
RETRY_DELAY = 3  # seconds
```

### 2. Lambda Layer 매핑 실패

```
[WARN] Layer 매핑 없음 -> arn:aws:lambda:...
```

**해결**: Layer가 마이그레이션되지 않았을 수 있습니다. `NAME_PREFIX` 필터 확인.

### 3. StepFunction 정의 오류

```
InvalidDefinition: Invalid State Machine Definition
```

**해결**:
- Lambda ARN이 잘못 교체되었을 수 있음
- 수동으로 상태 머신 정의 검토 필요
- `LAMBDA_ARN_MAP`이 올바르게 구성되었는지 확인

### 4. EventBridge 타겟 등록 실패

```
ResourceNotFoundException: Target not found
```

**해결**:
- Lambda나 Step Functions가 먼저 생성되었는지 확인
- Lambda에 EventBridge 호출 권한이 있는지 확인 (Resource Policy)

### 5. Step Functions Managed Rule 생성 실패 ⚠️

```
AccessDeniedException: 'arn:aws:iam::ACCOUNT:role/ROLE_NAME' is not authorized to create managed-rule
```

**원인**: Step Functions가 EventBridge와 통합될 때 자동으로 managed rule을 생성하는데, 실행 Role에 EventBridge 권한이 없거나 **Condition이 누락**되었을 때 발생합니다.

**해결 방법**:

1. **IAM Role 정책에 다음 Statement 추가** (Condition 포함 필수!):
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
         "events:ManagedBy": "states.amazonaws.com"
       }
     }
   }
   ```

2. **AWS Console에서 설정하는 경우**:
   - IAM > Roles > [Step Functions Role] > Permissions > Add permissions > Create inline policy
   - JSON 탭 선택 후 위 정책 붙여넣기
   - **중요**: `Condition` 블록을 반드시 포함해야 합니다!

3. **확인 방법**:
   - IAM Role의 정책에서 EventBridge 권한 확인
   - `Condition` 항목에 `"events:ManagedBy": "states.amazonaws.com"`가 있는지 확인

**주의사항**:
- ❌ EventBridge 권한만 있고 `Condition`이 없으면 → **여전히 오류 발생**
- ✅ EventBridge 권한 + `Condition` 포함 → **정상 작동**
- `states:*` 권한만으로는 부족하며, 반드시 `events:*` 관련 권한과 조건이 필요합니다.

**샘플 정책 파일**: `iam-policies/stepfunctions-role-policy.json` 참고

## 고급 사용법

### 특정 리소스만 마이그레이션

특정 접두사를 가진 리소스만 마이그레이션:

```bash
export NAME_PREFIX="prod-api-"
python migrate_aws_resources.py
```

### Dry-run 모드 (테스트용)

실제 생성 없이 확인만 하려면 코드 수정:

```python
# migrate_lambdas 함수에서
if not DRY_RUN:  # 상단에 DRY_RUN = False 추가
    lambda_dst.create_function(**params, Code={"ZipFile": zip_bytes})
```

### 커스텀 IAM Role 매핑

특정 함수별로 다른 Role을 사용하려면:

```python
ROLE_MAP = {
    "arn:aws:iam::111111111111:role/src-lambda-role-1": "arn:aws:iam::222222222222:role/dst-lambda-role-1",
    "arn:aws:iam::111111111111:role/src-lambda-role-2": "arn:aws:iam::222222222222:role/dst-lambda-role-2",
}
```

## 로그 확인

스크립트 실행 시 다음과 같은 로그가 출력됩니다:

```
2025-11-21 10:00:00 - INFO - 🚀 AWS 리소스 마이그레이션 시작
2025-11-21 10:00:01 - INFO - 소스 계정: 111111111111
2025-11-21 10:00:01 - INFO - 대상 계정: 222222222222
2025-11-21 10:00:02 - INFO - 🔐 EventBridge 실행 Role 생성
2025-11-21 10:00:03 - INFO - ➡ EventBridge Rules Role 생성: EventBridgeRulesExecutionRole
2025-11-21 10:00:04 - INFO -   ✔ Role 생성 완료: arn:aws:iam::222222222222:role/EventBridgeRulesExecutionRole
2025-11-21 10:00:05 - INFO -   ✔ Policy 첨부 완료
2025-11-21 10:00:15 - INFO - ➡ EventBridge Scheduler Role 생성: EventBridgeSchedulerExecutionRole
2025-11-21 10:00:16 - INFO -   ✔ Role 생성 완료: arn:aws:iam::222222222222:role/EventBridgeSchedulerExecutionRole
2025-11-21 10:00:17 - INFO -   ✔ Policy 첨부 완료
2025-11-21 10:00:27 - INFO - 🔧 Layer 자동 마이그레이션 시작
2025-11-21 10:00:30 - INFO - ✔ 매핑 등록: arn:aws:lambda:...
...
2025-11-21 10:05:00 - INFO - ✅ 전체 마이그레이션 완료!
2025-11-21 10:05:00 - INFO - 🔐 EventBridge 실행 Role: 생성 완료
2025-11-21 10:05:00 - INFO -    - Rules Role: arn:aws:iam::222222222222:role/EventBridgeRulesExecutionRole
2025-11-21 10:05:00 - INFO -    - Scheduler Role: arn:aws:iam::222222222222:role/EventBridgeSchedulerExecutionRole
2025-11-21 10:05:00 - INFO - 🔧 Layer: 5개
2025-11-21 10:05:00 - INFO - 🚀 Lambda: 25개
2025-11-21 10:05:00 - INFO - ⚙️ Step Functions: 3개
2025-11-21 10:05:00 - INFO - 📅 EventBridge Rules: 복제 완료
2025-11-21 10:05:00 - INFO - 📁 EventBridge Schedule Groups: 2개
2025-11-21 10:05:00 - INFO - ⏰ EventBridge Schedules: 복제 완료
```

# AWS Secrets Manager 마이그레이션

## 개요

`migrate_secrets_manager.py` 스크립트는 AWS Secrets Manager의 시크릿을 계정 간 마이그레이션하는 도구입니다.

## 마이그레이션 대상

- **시크릿 값**: 문자열 및 바이너리 시크릿
- **메타데이터**: 이름, 설명, 태그
- **KMS 암호화 키**: 커스텀 KMS 키 매핑 지원
- **버전 정보**: 현재 버전 및 스테이징 레이블

## 사용 방법

### 1. 환경 변수 설정

```bash
# 필수
export SRC_PROFILE="src"
export DST_PROFILE="dst"
export AWS_REGION="ap-northeast-2"

# 선택 (특정 이름 접두사만 마이그레이션)
export NAME_PREFIX="prod-"

# KMS 키 매핑 (선택적, JSON 형식)
export KMS_KEY_MAP='{"arn:aws:kms:ap-northeast-2:111111111111:key/src-key-id":"arn:aws:kms:ap-northeast-2:222222222222:key/dst-key-id"}'
```

### 2. 스크립트 실행

```bash
python migrate_secrets_manager.py
```

## 기능 상세

### ✅ 지원 기능

1. **시크릿 생성/업데이트**
   - 대상 계정에 시크릿이 없으면 새로 생성
   - 이미 존재하면 값 및 메타데이터 업데이트

2. **KMS 키 매핑**
   - 환경 변수로 KMS 키 매핑 지정 가능
   - AWS 관리형 키(`alias/aws/secretsmanager`) 자동 매핑
   - 매핑이 없으면 대상 계정의 기본 키 사용

3. **태그 복제**
   - 소스 시크릿의 모든 태그를 대상 시크릿에 복제
   - 기존 태그 제거 후 새 태그 적용

4. **메타데이터 복제**
   - Description
   - 버전 정보
   - 생성/수정 날짜

5. **에러 처리**
   - API Throttling 자동 재시도
   - 개별 시크릿 실패 시 다음 시크릿 계속 진행
   - 상세한 로그 및 통계 출력

### ⚠️ 제한 사항

1. **자동 회전 설정**
   - 자동 회전 설정은 Lambda 함수 ARN이 필요하므로 자동 마이그레이션되지 않음
   - 마이그레이션 후 수동으로 설정 필요
   - 스크립트가 회전 설정 정보를 로그에 출력

2. **리소스 정책**
   - 시크릿의 리소스 정책(Resource Policy)은 마이그레이션되지 않음
   - 필요시 수동으로 정책 복제 필요

3. **버전 히스토리**
   - 현재 버전만 마이그레이션됨
   - 이전 버전 히스토리는 복제되지 않음

4. **삭제 예정 시크릿**
   - `DeletedDate`가 설정된 시크릿은 자동으로 스킵됨

## KMS 키 매핑 예제

### 케이스 1: AWS 관리형 키 사용

소스와 대상 모두 AWS 관리형 키를 사용하는 경우, 별도 매핑 불필요:

```bash
# KMS_KEY_MAP 설정 없이 실행
python migrate_secrets_manager.py
```

### 케이스 2: 커스텀 KMS 키 매핑

커스텀 KMS 키를 사용하는 경우:

```bash
export KMS_KEY_MAP='{
  "arn:aws:kms:ap-northeast-2:111111111111:key/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee": "arn:aws:kms:ap-northeast-2:222222222222:key/ffffffff-gggg-hhhh-iiii-jjjjjjjjjjjj",
  "arn:aws:kms:ap-northeast-2:111111111111:key/11111111-2222-3333-4444-555555555555": "arn:aws:kms:ap-northeast-2:222222222222:key/66666666-7777-8888-9999-000000000000"
}'

python migrate_secrets_manager.py
```

### 케이스 3: 기본 키로 변경

커스텀 KMS 키를 사용하던 시크릿을 AWS 관리형 기본 키로 변경:

```bash
# KMS_KEY_MAP을 비워두면 자동으로 기본 키 사용
export KMS_KEY_MAP='{}'
python migrate_secrets_manager.py
```

## IAM 권한 요구사항

### 소스 계정

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:ListSecrets",
        "secretsmanager:DescribeSecret",
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "kms:Decrypt",
        "kms:DescribeKey"
      ],
      "Resource": "arn:aws:kms:*:*:key/*"
    }
  ]
}
```

### 대상 계정

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:CreateSecret",
        "secretsmanager:DescribeSecret",
        "secretsmanager:UpdateSecret",
        "secretsmanager:PutSecretValue",
        "secretsmanager:TagResource",
        "secretsmanager:UntagResource"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "kms:Encrypt",
        "kms:Decrypt",
        "kms:GenerateDataKey",
        "kms:DescribeKey"
      ],
      "Resource": "arn:aws:kms:*:*:key/*"
    }
  ]
}
```

## 로그 예시

```
2025-11-24 10:00:00 - INFO - 🔐 AWS Secrets Manager 마이그레이션 시작
2025-11-24 10:00:01 - INFO - 소스 계정: 111111111111
2025-11-24 10:00:01 - INFO - 대상 계정: 222222222222

==================================================
🔄 시크릿 마이그레이션 중: prod-api-key
==================================================
2025-11-24 10:00:02 - INFO -   시크릿 정보 조회 중...
2025-11-24 10:00:03 - INFO -   시크릿 값 조회 중...
2025-11-24 10:00:03 - INFO -   시크릿 버전: aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee
2025-11-24 10:00:03 - INFO -   버전 스테이지: AWSCURRENT
2025-11-24 10:00:04 - INFO -   새 시크릿 생성 필요
2025-11-24 10:00:04 - INFO -   KMS 키: 기본 키 사용
2025-11-24 10:00:05 - INFO -   새 시크릿 생성 중...
2025-11-24 10:00:06 - INFO -   ✔ 시크릿 생성 완료: arn:aws:secretsmanager:ap-northeast-2:222222222222:secret:prod-api-key-AbCdEf

==================================================
✅ Secrets Manager 마이그레이션 완료!
==================================================
📊 통계:
  - 전체 시크릿: 10개
  - 생성: 7개
  - 업데이트: 2개
  - 실패: 0개
  - 스킵: 1개
==================================================
```

## 트러블슈팅

### 1. KMS 권한 오류

```
AccessDeniedException: User is not authorized to perform: kms:Decrypt
```

**해결**:
- 소스 계정: KMS 키에 대한 `kms:Decrypt` 권한 확인
- 대상 계정: KMS 키에 대한 `kms:Encrypt`, `kms:GenerateDataKey` 권한 확인

### 2. 시크릿이 비어있음

```
[WARN] 시크릿 값이 없음 (비어있음)
```

**해결**: 이는 정상적인 경우로, 시크릿이 생성되었지만 값이 설정되지 않은 상태입니다. 필요시 수동으로 값 설정.

### 3. 자동 회전 설정 경고

```
⚠️  [주의] 소스 시크릿에 자동 회전이 활성화되어 있습니다
```

**해결**: 마이그레이션 후 대상 계정에서 수동으로 자동 회전 설정:

```bash
aws secretsmanager rotate-secret \
  --secret-id prod-api-key \
  --rotation-lambda-arn arn:aws:lambda:ap-northeast-2:222222222222:function:rotation-function \
  --rotation-rules AutomaticallyAfterDays=30
```

### 4. Throttling 에러

```
TooManyRequestsException: Rate exceeded
```

**해결**: 스크립트가 자동으로 재시도하지만, 대량의 시크릿을 마이그레이션할 때는 배치 단위로 나누어 실행하는 것을 권장:

```bash
# 배치 1
export NAME_PREFIX="prod-api-"
python migrate_secrets_manager.py

# 배치 2
export NAME_PREFIX="prod-db-"
python migrate_secrets_manager.py
```

## 보안 권장사항

1. **시크릿 값 보안**
   - 마이그레이션 후 불필요한 소스 시크릿은 삭제
   - 민감한 시크릿은 마이그레이션 후 값 변경 권장

2. **KMS 키 관리**
   - 프로덕션 환경에서는 AWS 관리형 키보다 커스텀 KMS 키 사용 권장
   - KMS 키 정책에서 최소 권한 원칙 적용

3. **감사 로깅**
   - CloudTrail에서 Secrets Manager API 호출 모니터링
   - 마이그레이션 전후 시크릿 접근 로그 확인

4. **VPC 엔드포인트**
   - 프라이빗 서브넷에서 실행되는 애플리케이션의 경우 VPC 엔드포인트 설정
   - 대상 계정에도 동일한 VPC 엔드포인트 구성 필요

## 라이선스

MIT License

## 기여

버그 리포트나 기능 제안은 이슈로 등록해주세요.
