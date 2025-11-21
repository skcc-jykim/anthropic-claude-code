# AWS 리소스 Cleanup 스크립트

마이그레이션 중 오류가 발생했을 때, 타겟 계정에 생성된 리소스를 삭제하는 스크립트입니다.

## 개요

`cleanup_migrated_resources.py`는 소스 계정의 리소스 이름을 기준으로 타겟 계정에서 동일한 이름의 리소스를 찾아 삭제합니다.

## 삭제되는 리소스

다음 리소스들이 의존성 역순으로 삭제됩니다:

1. **EventBridge Rules** - Lambda, Step Functions를 참조하므로 먼저 삭제
2. **Step Functions** - Lambda를 참조하므로 두 번째로 삭제
3. **Lambda Functions** - Layer를 참조하므로 세 번째로 삭제
4. **Lambda Layers** - 마지막으로 삭제

## 사용법

### 1. 기본 사용법

```bash
python3 cleanup_migrated_resources.py
```

### 2. 환경 변수 설정

마이그레이션 스크립트와 동일한 환경 변수를 사용합니다:

```bash
export SRC_PROFILE="src"           # 소스 AWS 프로파일
export DST_PROFILE="dst"           # 타겟 AWS 프로파일
export AWS_REGION="ap-northeast-2" # AWS 리전
export NAME_PREFIX=""              # 이름 접두사 필터 (선택사항)

python3 cleanup_migrated_resources.py
```

### 3. 특정 접두사로 필터링

특정 접두사로 시작하는 리소스만 삭제하려면:

```bash
export NAME_PREFIX="my-service-"
python3 cleanup_migrated_resources.py
```

## 실행 프로세스

1. **리소스 미리보기**: 삭제될 리소스 목록을 표시합니다
2. **사용자 확인**: 삭제를 진행할지 확인합니다 (yes/no)
3. **순차 삭제**: 의존성 역순으로 리소스를 삭제합니다
4. **결과 요약**: 삭제된 리소스 개수를 표시합니다

## 실행 예시

```
$ python3 cleanup_migrated_resources.py

======================================================================
🗑️  AWS 리소스 정리 (Cleanup) 시작
======================================================================
소스 프로파일: src
대상 프로파일: dst
리전: ap-northeast-2
이름 접두사 필터: (전체)
======================================================================
소스 계정: 123456789012
대상 계정: 846697434179 (여기서 리소스 삭제됨)

==================================================
📋 삭제될 리소스 미리보기
==================================================

📦 Lambda Layers: 2개
  - pandas-layer
  - requests-layer

⚡ Lambda Functions: 5개
  - my-function-1
  - my-function-2
  - my-function-3
  - my-function-4
  - my-function-5

⚙️  Step Functions: 2개
  - my-workflow-1
  - my-workflow-2

📅 EventBridge Rules: 3개
  - schedule-rule-1
  - schedule-rule-2
  - event-rule-1

==================================================

⚠️  위 리소스들을 모두 삭제하시겠습니까? (yes/no): yes

🗑️  리소스 삭제를 시작합니다...

==================================================
🗑️  EventBridge 규칙 삭제 시작
==================================================
...

======================================================================
✅ 전체 리소스 정리 완료!
======================================================================
EventBridge Rules: 3개 삭제
Step Functions: 2개 삭제
Lambda Functions: 5개 삭제
Lambda Layers: 2개 삭제
======================================================================
```

## 안전 기능

1. **실행 전 미리보기**: 삭제될 리소스를 미리 확인할 수 있습니다
2. **사용자 확인**: 명시적으로 'yes'를 입력해야 삭제가 진행됩니다
3. **존재 여부 확인**: 타겟 계정에 리소스가 존재하는 경우에만 삭제를 시도합니다
4. **오류 처리**: 개별 리소스 삭제 실패 시 다음 리소스로 계속 진행합니다
5. **재시도 로직**: API throttling 발생 시 자동으로 재시도합니다

## 주의사항

⚠️ **경고**: 이 스크립트는 타겟 계정의 리소스를 **영구적으로 삭제**합니다. 실행 전 반드시:

1. 올바른 AWS 프로파일이 설정되어 있는지 확인하세요
2. 삭제될 리소스 목록을 신중히 검토하세요
3. 필요한 경우 백업을 먼저 수행하세요

## 문제 해결

### 권한 오류

타겟 계정의 AWS 프로파일에 다음 권한이 필요합니다:

- `lambda:DeleteFunction`
- `lambda:DeleteLayerVersion`
- `lambda:ListFunctions`
- `lambda:ListLayers`
- `lambda:ListLayerVersions`
- `states:DeleteStateMachine`
- `states:ListStateMachines`
- `events:DeleteRule`
- `events:ListRules`
- `events:ListTargetsByRule`
- `events:RemoveTargets`

### Throttling 오류

API 호출 제한에 도달하면 자동으로 재시도합니다. 최대 3회까지 지수 백오프로 재시도합니다.

## 관련 파일

- `migrate_aws_resources.py` - 마이그레이션 스크립트
- `cleanup_migrated_resources.py` - 이 cleanup 스크립트
