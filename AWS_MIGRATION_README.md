# AWS 리소스 마이그레이션 도구

AWS 계정 간 Lambda, Step Functions, EventBridge 규칙을 자동으로 마이그레이션하는 Python 스크립트입니다.

## 주요 기능

### ✅ 마이그레이션 대상 리소스

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

### 🔧 개선 사항 (기존 코드 대비)

1. **로깅 시스템**
   - `print` 대신 `logging` 모듈 사용
   - 타임스탬프 및 로그 레벨 포함

2. **에러 처리**
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

1. **Lambda Layers** - Lambda가 의존하는 Layer를 먼저 복제
2. **Lambda Functions** - 함수 코드 및 설정 복제
3. **Step Functions** - 상태 머신 정의 복제 (Lambda ARN 자동 업데이트)
4. **EventBridge Rules** - 이벤트 규칙 및 타겟 복제

## 주의사항

### ⚠️ 사전 확인 필요

1. **IAM 권한**
   - 소스 계정: Lambda, Step Functions, EventBridge 읽기 권한
   - 대상 계정: 위 서비스들의 생성/수정 권한

2. **네트워크 리소스**
   - VPC, 서브넷, 보안 그룹이 대상 계정에 미리 생성되어 있어야 함
   - `SUBNET_MAP`, `SG_MAP`에 정확한 매핑 설정 필요

3. **IAM Role**
   - Lambda 및 Step Functions 실행 Role이 대상 계정에 준비되어야 함
   - `DEFAULT_DEST_LAMBDA_ROLE`, `DEFAULT_DEST_SFN_ROLE` 환경 변수 설정

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
2025-11-21 10:00:02 - INFO - 🔧 Layer 자동 마이그레이션 시작
2025-11-21 10:00:05 - INFO - ✔ 매핑 등록: arn:aws:lambda:...
...
2025-11-21 10:05:00 - INFO - ✅ 전체 마이그레이션 완료!
2025-11-21 10:05:00 - INFO - Layer: 5개
2025-11-21 10:05:00 - INFO - Lambda: 25개
2025-11-21 10:05:00 - INFO - Step Functions: 3개
```

## 라이선스

MIT License

## 기여

버그 리포트나 기능 제안은 이슈로 등록해주세요.
