# AWS 리소스 마이그레이션 스크립트

AWS 계정 간 리소스를 마이그레이션하기 위한 Python 스크립트 모음입니다.

## 📋 지원하는 리소스

### 1. migrate_aws_resources.py
다음 AWS 리소스들을 소스 계정에서 대상 계정으로 마이그레이션합니다:

- ✅ **Lambda Layers** - 자동 복제 및 매핑
- ✅ **Lambda Functions** - 코드, 설정, 환경변수, VPC, 태그, 동시성 등
- ✅ **Step Functions** - 상태 머신 정의 및 ARN 교체
- ✅ **EventBridge Rules** - 규칙 및 타겟
- ✅ **EventBridge Scheduler** - 일정 그룹 및 일정

### 2. migrate_api_gateway.py
API Gateway 리소스를 마이그레이션합니다:

- ✅ **REST APIs** - OpenAPI 정의 기반 Export/Import
- ✅ **Stages** - Deployment 및 설정
- ✅ **API Keys** - 키 및 설정
- ✅ **Usage Plans** - 할당량, 스로틀링, API 연결

### 3. migrate_secrets_manager.py
AWS Secrets Manager 리소스를 마이그레이션합니다:

- ✅ **Secrets** - 시크릿 값 및 메타데이터
- ✅ **Tags** - 태그 복제
- ✅ **Rotation** - 자동 로테이션 설정

### 4. verify_migration_from_excel.py
엑셀 파일로 관리하는 마이그레이션 체크리스트를 기반으로 실제 이관 완료 여부를 검증합니다:

- ✅ **Lambda** - 함수 존재 여부 확인
- ✅ **Step Functions** - 상태 머신 존재 여부 확인
- ✅ **EventBridge Rules** - 규칙 존재 여부 확인
- ✅ **EventBridge Scheduler** - 스케줄 존재 여부 확인
- ✅ **API Gateway** - REST API 존재 여부 확인
- ✅ **Secrets Manager** - 시크릿 존재 여부 확인
- ✅ **엑셀 결과 출력** - 검증 결과를 엑셀 파일로 저장

## 🚀 사용 방법

### 사전 요구사항

1. **Python 3.7+** 설치
2. **boto3, openpyxl** 라이브러리 설치:
   ```bash
   pip install boto3 requests openpyxl
   ```

3. **AWS 자격증명 설정**:
   - `~/.aws/credentials` 파일에 소스 및 대상 계정 프로파일 설정
   ```ini
   [src]
   aws_access_key_id = YOUR_SOURCE_ACCESS_KEY
   aws_secret_access_key = YOUR_SOURCE_SECRET_KEY

   [dst]
   aws_access_key_id = YOUR_DEST_ACCESS_KEY
   aws_secret_access_key = YOUR_DEST_SECRET_KEY
   ```

### Lambda, Step Functions, EventBridge 마이그레이션

```bash
# 환경변수 설정
export SRC_PROFILE=src
export DST_PROFILE=dst
export AWS_REGION=ap-northeast-2
export NAME_PREFIX=""  # 특정 접두사로 시작하는 리소스만 마이그레이션하려면 설정

# IAM Role 매핑 설정
export DEFAULT_DEST_LAMBDA_ROLE="arn:aws:iam::TARGET_ACCOUNT:role/lambda-role"
export DEFAULT_DEST_SFN_ROLE="arn:aws:iam::TARGET_ACCOUNT:role/stepfunctions-role"

# EventBridge 실행 Role (선택사항 - 미설정 시 자동 생성)
export EVENTBRIDGE_RULES_ROLE_ARN="arn:aws:iam::TARGET_ACCOUNT:role/EventBridgeRulesRole"
export EVENTBRIDGE_SCHEDULER_ROLE_ARN="arn:aws:iam::TARGET_ACCOUNT:role/EventBridgeSchedulerRole"

# 실행
python3 migrate_aws_resources.py
```

### API Gateway 마이그레이션

```bash
# 환경변수 설정
export SRC_PROFILE=src
export DST_PROFILE=dst
export AWS_REGION=ap-northeast-2
export NAME_PREFIX=""  # 특정 접두사로 시작하는 리소스만 마이그레이션하려면 설정

# Lambda ARN 매핑 (선택사항 - Lambda 통합이 있는 경우)
# migrate_aws_resources.py를 먼저 실행한 경우 매핑 JSON을 환경변수로 전달
export LAMBDA_ARN_MAP='{
  "arn:aws:lambda:ap-northeast-2:111111111111:function:func1": "arn:aws:lambda:ap-northeast-2:222222222222:function:func1",
  "arn:aws:lambda:ap-northeast-2:111111111111:function:func2": "arn:aws:lambda:ap-northeast-2:222222222222:function:func2"
}'

# 실행
python3 migrate_api_gateway.py
```

### Secrets Manager 마이그레이션

```bash
# 환경변수 설정
export SRC_PROFILE=src
export DST_PROFILE=dst
export AWS_REGION=ap-northeast-2
export NAME_PREFIX=""  # 특정 접두사로 시작하는 리소스만 마이그레이션하려면 설정

# 실행
python3 migrate_secrets_manager.py
```

### 마이그레이션 검증 (엑셀 기반)

```bash
# 1. 엑셀 템플릿 생성
python3 create_migration_checklist_template.py

# 또는 커스텀 파일명으로 생성
python3 create_migration_checklist_template.py -o my_checklist.xlsx

# 2. 생성된 엑셀 파일에 마이그레이션 대상 리소스 입력
#    - 리소스 타입: Lambda, StepFunction, EventBridgeRule, EventBridgeSchedule, APIGateway, SecretsManager
#    - 리소스 이름: AWS 리소스 이름 (ARN 아님)
#    - 소스/대상 계정 ID 입력

# 3. 입력 완료 후 파일을 'migration_checklist.xlsx'로 저장

# 4. 검증 스크립트 실행
export DST_PROFILE=dst
export AWS_REGION=ap-northeast-2
export EXCEL_FILE_PATH=migration_checklist.xlsx
export OUTPUT_FILE_PATH=migration_verification_result.xlsx

python3 verify_migration_from_excel.py

# 5. 결과 확인
#    - migration_verification_result.xlsx 파일 확인
#    - 이관 완료: 녹색 배경
#    - 이관 미완료: 빨간색 배경
#    - 콘솔에서도 요약 통계 확인 가능
```

## 📝 주요 기능

### migrate_aws_resources.py

#### 1. 의존성 순서 처리
- IAM Role → Layers → Lambda → Step Functions → EventBridge 순서로 마이그레이션
- 리소스 간 의존성을 자동으로 처리

#### 2. ARN 자동 매핑
- Lambda ARN 매핑 테이블 자동 생성
- Step Functions 정의에서 Lambda ARN 자동 교체
- EventBridge 타겟 ARN 자동 교체

#### 3. Create/Update 패턴
- 기존 리소스가 있으면 업데이트
- 없으면 새로 생성
- 멱등성 보장 (여러 번 실행해도 안전)

#### 4. 재시도 메커니즘
- API Throttling 자동 재시도
- 지수 백오프 (2초, 4초, 8초...)

#### 5. 태그 복제
- 모든 리소스의 태그 자동 복제

### migrate_api_gateway.py

#### 1. OpenAPI 기반 마이그레이션
- API를 OpenAPI 3.0 형식으로 Export
- Lambda ARN 자동 교체
- Import를 통한 정확한 복제

#### 2. Stage 설정 복제
- Deployment 자동 생성
- Cache, Throttling, Tracing 설정 복제
- Stage Variables 복제

#### 3. API Key 및 Usage Plan
- API Key 값 복제 (가능한 경우)
- Usage Plan과 API 연결 자동 매핑
- 할당량 및 스로틀링 설정 복제

### verify_migration_from_excel.py

#### 1. 엑셀 기반 체크리스트 관리
- 마이그레이션 대상 리소스를 엑셀로 관리
- 리소스 타입, 이름, 계정 정보 입력
- 검증 결과 자동 업데이트

#### 2. 다중 리소스 타입 지원
- Lambda, Step Functions, EventBridge, API Gateway, Secrets Manager
- 각 리소스 타입별 자동 검증
- 존재 여부 실시간 확인

#### 3. 시각적 결과 표시
- 이관 완료: 녹색 배경
- 이관 미완료: 빨간색 배경
- 검증 일시 자동 기록
- 비고 필드에 상세 정보

#### 4. 통계 및 리포팅
- 전체 이관 진행률
- 리소스 타입별 통계
- 미완료 리소스 목록 출력
- 엑셀 파일로 결과 저장

## ⚙️ 설정 옵션

### 환경변수

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `SRC_PROFILE` | 소스 계정 AWS 프로파일 | `src` |
| `DST_PROFILE` | 대상 계정 AWS 프로파일 | `dst` |
| `AWS_REGION` | AWS 리전 | `ap-northeast-2` |
| `NAME_PREFIX` | 리소스 이름 필터 (접두사) | `` (전체) |
| `DEFAULT_DEST_LAMBDA_ROLE` | Lambda 기본 실행 Role ARN | (필수) |
| `DEFAULT_DEST_SFN_ROLE` | Step Functions 기본 실행 Role ARN | (필수) |
| `EVENTBRIDGE_RULES_ROLE_ARN` | EventBridge Rules 실행 Role ARN | (자동 생성) |
| `EVENTBRIDGE_SCHEDULER_ROLE_ARN` | EventBridge Scheduler 실행 Role ARN | (자동 생성) |
| `LAMBDA_ARN_MAP` | Lambda ARN 매핑 JSON | `{}` |
| `EXCEL_FILE_PATH` | 입력 엑셀 파일 경로 (검증 스크립트) | `migration_checklist.xlsx` |
| `OUTPUT_FILE_PATH` | 출력 엑셀 파일 경로 (검증 스크립트) | `migration_verification_result.xlsx` |
| `SHEET_NAME` | 엑셀 시트 이름 (검증 스크립트) | `Migration List` |

### 코드 내 매핑 설정

`migrate_aws_resources.py` 파일 내에서 다음 매핑을 수정할 수 있습니다:

```python
# 서브넷 매핑
SUBNET_MAP = {
    "subnet-SOURCE1": "subnet-DEST1",
    "subnet-SOURCE2": "subnet-DEST2"
}

# Security Group 매핑
SG_MAP = {
    "sg-SOURCE": "sg-DEST",
}

# IAM Role 매핑 (세밀한 제어가 필요한 경우)
ROLE_MAP = {
    "arn:aws:iam::SRC_ACCOUNT:role/source-role": "arn:aws:iam::DST_ACCOUNT:role/dest-role"
}
```

## 🔍 실행 흐름

### migrate_aws_resources.py
```
1. EventBridge 실행 Role 생성/확인
2. Lambda Layers 마이그레이션
   └─> LAYER_MAP 생성
3. Lambda Functions 마이그레이션
   └─> LAMBDA_ARN_MAP 생성
4. Step Functions 마이그레이션
   └─> Lambda ARN 교체
   └─> SFN_ARN_MAP 생성
5. EventBridge Rules 마이그레이션
   └─> 타겟 ARN 교체
6. EventBridge Scheduler 그룹 마이그레이션
7. EventBridge Scheduler 일정 마이그레이션
   └─> 타겟 ARN 교체
```

### migrate_api_gateway.py
```
1. REST APIs 마이그레이션
   ├─> OpenAPI 정의 Export
   ├─> Lambda ARN 교체
   ├─> Import (생성/업데이트)
   ├─> 태그 복제
   └─> Stages 마이그레이션
       ├─> Deployment 생성
       ├─> Stage 설정 복제
       └─> 태그 복제
2. API Keys 마이그레이션
   ├─> API Key 생성
   └─> 태그 복제
3. Usage Plans 마이그레이션
   ├─> Usage Plan 생성
   ├─> API Stages 연결
   ├─> API Keys 연결
   └─> 태그 복제
```

## ⚠️ 주의사항

### 공통
1. **IAM 권한**: 소스 및 대상 계정 모두 충분한 권한 필요
2. **VPC/Subnet/Security Group**: 대상 계정에 미리 생성되어 있어야 함
3. **계정 한도**: 대상 계정의 서비스 한도 확인 필요
4. **비용**: 리소스 복제 시 비용 발생 가능

### migrate_aws_resources.py
1. **Container 이미지 Lambda**: ECR 이미지는 별도 마이그레이션 필요
2. **EventBridge 커스텀 버스**: 현재는 default 버스만 지원
3. **Step Functions 로깅/추적**: 권한 문제로 비활성화됨

### migrate_api_gateway.py
1. **Lambda 권한 추가**: API Gateway가 Lambda를 호출하려면 추가 권한 필요
   ```bash
   aws lambda add-permission \
     --function-name <LAMBDA_NAME> \
     --statement-id apigateway-invoke \
     --action lambda:InvokeFunction \
     --principal apigateway.amazonaws.com \
     --source-arn "arn:aws:execute-api:REGION:ACCOUNT:API_ID/*" \
     --profile dst
   ```

2. **Custom Domain**: 커스텀 도메인은 별도 설정 필요
3. **VPC Link**: VPC Link는 별도 마이그레이션 필요
4. **API Gateway v2 (HTTP/WebSocket)**: 현재는 REST API만 지원

### verify_migration_from_excel.py
1. **엑셀 파일 형식**:
   - 'Migration List' 시트 이름 필수
   - 헤더 행(첫 번째 행) 삭제 금지
   - 리소스 타입은 정확하게 입력 (대소문자 구분)

2. **리소스 이름 형식**:
   - Lambda: 함수 이름만 (ARN 아님)
   - StepFunction: 상태 머신 이름만
   - EventBridgeSchedule: `그룹명/스케줄명` 또는 `스케줄명`만
   - 기타: 리소스 이름만

3. **권한**: 대상 계정에 리소스 조회 권한 필요
4. **openpyxl 라이브러리**: `pip install openpyxl` 필수

## 🔒 보안 고려사항

1. **자격증명 관리**: AWS 프로파일 사용 (하드코딩 금지)
2. **최소 권한 원칙**: 필요한 권한만 부여
3. **감사 로그**: CloudTrail에서 모든 작업 추적 가능
4. **암호화**: KMS 키는 계정 간 교체됨 (대상 계정의 키 사용)

## 📊 로그

실행 중 다음과 같은 정보가 로깅됩니다:
- ✔ 성공한 작업
- ⚠ 경고 (건너뛴 리소스, 태그 복제 실패 등)
- ❌ 오류 (개별 리소스 실패 시에도 계속 진행)

## 🛠 트러블슈팅

### Throttling 오류
```
TooManyRequestsException
```
→ 스크립트가 자동으로 재시도합니다. MAX_RETRIES 및 RETRY_DELAY 조정 가능

### 권한 오류
```
AccessDeniedException
```
→ IAM 권한 확인 필요

### ARN 매핑 오류
```
No mapping found for ARN
```
→ 계정 ID만 교체됩니다. 필요시 수동으로 ARN 확인 필요

## 📚 참고 자료

- [AWS Lambda Documentation](https://docs.aws.amazon.com/lambda/)
- [AWS Step Functions Documentation](https://docs.aws.amazon.com/step-functions/)
- [AWS EventBridge Documentation](https://docs.aws.amazon.com/eventbridge/)
- [AWS API Gateway Documentation](https://docs.aws.amazon.com/apigateway/)

## 📄 라이선스

이 프로젝트는 내부 사용을 위한 도구입니다.

## 🤝 기여

개선사항이나 버그 리포트는 이슈로 등록해주세요.
