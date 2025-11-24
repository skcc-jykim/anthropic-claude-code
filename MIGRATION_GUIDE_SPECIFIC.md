# 특정 리소스 마이그레이션 가이드

이 가이드는 지정된 특정 리소스만 선택적으로 마이그레이션하는 방법을 설명합니다.

## 📋 마이그레이션 대상 리소스

- **Lambda 함수**: 48개 (target_lambdas.txt)
- **Step Functions**: 61개 (target_stepfunctions.txt)
- **EventBridge Schedules**: 65개 (target_schedules.txt)
- **총 리소스**: 174개

## 📁 파일 구조

```
anthropic-claude-code/
├── migrate_aws_resources.py          # 기존 마이그레이션 스크립트
├── migrate_specific_resources.py     # 리소스 목록 검증 스크립트
├── migrate_specific_resources_runner.py  # 실제 마이그레이션 실행 스크립트
├── target_lambdas.txt                # Lambda 함수 목록
├── target_stepfunctions.txt          # Step Functions 목록
├── target_schedules.txt              # EventBridge Schedules 목록
└── MIGRATION_GUIDE_SPECIFIC.md       # 이 가이드
```

## 🚀 사용 방법

### 1. 사전 준비

#### 1.1 AWS 프로파일 설정

```bash
# ~/.aws/config 또는 ~/.aws/credentials 에 프로파일 설정
[profile src]
region = ap-northeast-2
# ... 소스 계정 크레덴셜

[profile dst]
region = ap-northeast-2
# ... 대상 계정 크레덴셜
```

#### 1.2 환경 변수 설정

```bash
export SRC_PROFILE=src
export DST_PROFILE=dst
export AWS_REGION=ap-northeast-2
```

#### 1.3 필요한 Python 패키지 설치

```bash
pip install boto3 requests
```

#### 1.4 Docker 설치 (컨테이너 이미지 Lambda가 있는 경우)

```bash
# Docker가 설치되어 있고 실행 중인지 확인
docker --version
docker ps
```

### 2. 리소스 목록 검증

실제 마이그레이션을 실행하기 전에 리소스 목록을 검증합니다:

```bash
python migrate_specific_resources.py
```

출력 예시:
```
================================================================================
📊 마이그레이션 대상 리소스 요약
================================================================================
🚀 Lambda 함수: 48개
⚙️  Step Functions: 61개
⏰ EventBridge Schedules: 65개
📦 총 리소스: 174개
================================================================================
```

### 3. 마이그레이션 실행

#### 3.1 전체 마이그레이션 (추천)

모든 대상 리소스를 한 번에 마이그레이션:

```bash
python migrate_specific_resources_runner.py
```

#### 3.2 Lambda만 마이그레이션

```bash
# target_stepfunctions.txt와 target_schedules.txt를 임시로 비우거나
# 또는 스크립트를 수정하여 Lambda만 마이그레이션
```

#### 3.3 환경 변수를 사용한 Lambda 선택적 마이그레이션

기존 `migrate_aws_resources.py` 스크립트를 사용하는 방법:

```bash
export LAMBDA_FUNCTIONS_FILE=target_lambdas.txt
python migrate_aws_resources.py
```

### 4. 마이그레이션 단계별 설명

`migrate_specific_resources_runner.py`는 다음 순서로 마이그레이션을 진행합니다:

1. **리소스 목록 로드**: target_*.txt 파일 읽기
2. **EventBridge 실행 Role 생성**: Scheduler 및 Rules 실행에 필요한 IAM Role 생성
3. **Lambda 함수 마이그레이션**:
   - ZIP 기반 Lambda: 코드 다운로드 및 업로드
   - 컨테이너 이미지 Lambda: ECR 이미지 복사
   - Layer 의존성 자동 수집
4. **Layer 마이그레이션**: Lambda가 사용하는 Layer만 선택적으로 마이그레이션
5. **Step Functions 마이그레이션**: 상태 머신 정의 및 ARN 교체
6. **EventBridge Schedules 마이그레이션**: 일정 및 타겟 ARN 교체

## 📝 리소스 목록 파일 형식

### target_lambdas.txt

```
# Lambda functions to migrate
alert-pv_tot_anml_dtct
check-analyze-env-ip
collector-param_setting-kpx
...
```

### target_stepfunctions.txt

```
# Step Functions to migrate
collector-kpx-meter_for_settlement_k2
model_plnt-whtr-obsr-mapping_workflow
...
```

### target_schedules.txt

```
# EventBridge Schedules to migrate
kpx/collector-kpx-meter_for_settlement_k2
retry/collector_retry-weatherdata-aws-24h
wd-processing/weatherdata-aws
...
```

**참고**:
- `#`으로 시작하는 줄은 주석으로 무시됩니다
- 빈 줄도 무시됩니다
- 각 리소스 이름은 한 줄에 하나씩 작성합니다

## ⚙️ 고급 설정

### Layer 처리 옵션

```bash
# Layer가 없어도 Lambda 마이그레이션 계속 진행 (기본값)
export SKIP_MISSING_LAYERS=true

# Layer 매핑 실패 시 마이그레이션 중단
export FAIL_ON_MISSING_LAYERS=true
```

### IAM Role 매핑

기본적으로 다음 Role이 사용됩니다:

```python
DEFAULT_DEST_LAMBDA_ROLE = "arn:aws:iam::846697434179:role/skies-dp-prd-dip-lambda-default-role"
DEFAULT_DEST_SFN_ROLE = "arn:aws:iam::846697434179:role/skies-dp-prd-dip-sfn-default-role"
```

다른 Role을 사용하려면 환경 변수로 설정:

```bash
export DEFAULT_DEST_LAMBDA_ROLE="arn:aws:iam::ACCOUNT:role/YOUR-LAMBDA-ROLE"
export DEFAULT_DEST_SFN_ROLE="arn:aws:iam::ACCOUNT:role/YOUR-SFN-ROLE"
```

### EventBridge 실행 Role

EventBridge Role은 자동으로 생성되지만, 기존 Role을 사용하려면:

```bash
export EVENTBRIDGE_RULES_ROLE_ARN="arn:aws:iam::ACCOUNT:role/YOUR-EVENTBRIDGE-RULES-ROLE"
export EVENTBRIDGE_SCHEDULER_ROLE_ARN="arn:aws:iam::ACCOUNT:role/YOUR-SCHEDULER-ROLE"
```

## 🔍 트러블슈팅

### 1. Lambda 함수를 찾을 수 없음

```
⚠️  Lambda 함수를 찾을 수 없음: function-name
```

**해결 방법**:
- 소스 계정에 해당 Lambda 함수가 존재하는지 확인
- 함수 이름이 정확한지 확인 (대소문자 구분)
- AWS 프로파일과 리전 설정 확인

### 2. Layer 마이그레이션 실패

```
❌ Layer 마이그레이션 실패: ...
```

**해결 방법**:
- 소스 계정의 Layer 접근 권한 확인
- `SKIP_MISSING_LAYERS=true` 설정하여 Layer 없이 진행
- Layer를 수동으로 마이그레이션

### 3. ECR 이미지 복사 실패

```
❌ ECR 이미지 마이그레이션 실패: ...
```

**해결 방법**:
- Docker가 실행 중인지 확인
- ECR 접근 권한 확인
- 대상 계정의 ECR 저장소 권한 확인

### 4. EventBridge Role 생성 실패

```
❌ EventBridge Rules Role 생성 실패: ...
```

**해결 방법**:
- IAM 생성 권한 확인
- `iam-policies/` 디렉토리에 필요한 정책 파일 존재 확인
- 기존 Role ARN을 환경 변수로 제공

### 5. StepFunction 정의 오류

```
❌ 생성/업데이트 실패: Invalid State Machine Definition
```

**해결 방법**:
- ARN 매핑이 올바른지 확인
- Lambda ARN이 대상 계정에 존재하는지 확인
- 수동으로 StepFunction 정의 검증

## 📊 마이그레이션 결과 확인

마이그레이션 완료 후 다음을 확인하세요:

### Lambda 함수

```bash
# 대상 계정에서 Lambda 함수 확인
aws lambda list-functions --profile dst --region ap-northeast-2 \
  --query 'Functions[].FunctionName' --output table
```

### Step Functions

```bash
# 대상 계정에서 Step Functions 확인
aws stepfunctions list-state-machines --profile dst --region ap-northeast-2 \
  --query 'stateMachines[].name' --output table
```

### EventBridge Schedules

```bash
# 대상 계정에서 Schedules 확인
aws scheduler list-schedules --profile dst --region ap-northeast-2 \
  --query 'Schedules[].Name' --output table
```

## 🔄 재실행 및 업데이트

스크립트는 멱등성(idempotent)을 지원합니다:

- 이미 존재하는 리소스는 **업데이트**됩니다
- 없는 리소스는 **새로 생성**됩니다

따라서 마이그레이션을 여러 번 실행해도 안전합니다.

## ⚠️  주의사항

1. **소스 리소스 보존**: 이 스크립트는 소스 리소스를 삭제하지 않습니다
2. **대상 리소스 덮어쓰기**: 대상에 같은 이름의 리소스가 있으면 업데이트됩니다
3. **비용**: ECR 이미지 전송, Lambda 실행 등에 비용이 발생할 수 있습니다
4. **권한**: 소스 계정 읽기 권한, 대상 계정 쓰기 권한 필요
5. **네트워크**: VPC 설정은 자동으로 매핑되지만, 대상 계정에 해당 VPC/Subnet이 존재해야 합니다

## 📞 문제 해결

마이그레이션 중 문제가 발생하면:

1. 로그 메시지를 자세히 확인
2. AWS 콘솔에서 리소스 상태 확인
3. IAM 권한 확인
4. 이 가이드의 트러블슈팅 섹션 참고

## 🎯 다음 단계

마이그레이션 완료 후:

1. 대상 계정에서 리소스 동작 테스트
2. EventBridge 일정 활성화 상태 확인
3. Lambda 함수 테스트 실행
4. Step Functions 상태 머신 테스트
5. 필요시 소스 리소스 정리
