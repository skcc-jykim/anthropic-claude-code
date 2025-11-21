#!/bin/bash

ROLE_NAME="skies-dp-prd-dip-sfn-default-role"
PROFILE="dst"
REGION="ap-northeast-2"

echo "========================================"
echo "IAM Role 상세 진단: $ROLE_NAME"
echo "========================================"

echo -e "\n1️⃣  Trust Relationship 확인"
echo "----------------------------------------"
aws iam get-role --role-name $ROLE_NAME --profile $PROFILE \
  --query 'Role.AssumeRolePolicyDocument' --output json

echo -e "\n2️⃣  Permission Boundary 확인"
echo "----------------------------------------"
BOUNDARY=$(aws iam get-role --role-name $ROLE_NAME --profile $PROFILE \
  --query 'Role.PermissionsBoundary' --output text 2>/dev/null)
if [ "$BOUNDARY" = "None" ] || [ -z "$BOUNDARY" ]; then
  echo "✅ Permission Boundary 없음 (정상)"
else
  echo "⚠️  Permission Boundary 발견: $BOUNDARY"
  echo "    이것이 EventBridge 권한을 제한하고 있을 수 있습니다!"
fi

echo -e "\n3️⃣  연결된 Managed 정책 목록"
echo "----------------------------------------"
aws iam list-attached-role-policies --role-name $ROLE_NAME --profile $PROFILE --output table

echo -e "\n4️⃣  Inline 정책 목록"
echo "----------------------------------------"
INLINE_POLICIES=$(aws iam list-role-policies --role-name $ROLE_NAME --profile $PROFILE \
  --query 'PolicyNames' --output text)

if [ -z "$INLINE_POLICIES" ]; then
  echo "Inline 정책 없음"
else
  echo "발견된 Inline 정책: $INLINE_POLICIES"

  echo -e "\n5️⃣  각 Inline 정책 상세 내용"
  echo "----------------------------------------"
  for policy in $INLINE_POLICIES; do
    echo -e "\n📄 정책 이름: $policy"
    echo "---"
    aws iam get-role-policy --role-name $ROLE_NAME --policy-name "$policy" --profile $PROFILE \
      --query 'PolicyDocument' --output json

    # Deny 검사
    DENY_COUNT=$(aws iam get-role-policy --role-name $ROLE_NAME --policy-name "$policy" --profile $PROFILE \
      --query 'PolicyDocument' --output json | grep -c '"Effect".*"Deny"')
    if [ "$DENY_COUNT" -gt 0 ]; then
      echo "⚠️  이 정책에 Deny Statement가 $DENY_COUNT 개 있습니다!"
    fi
  done
fi

echo -e "\n6️⃣  EventBridge 권한 확인"
echo "----------------------------------------"
echo "EventBridge 권한이 있는 Statement 검색 중..."

for policy in $INLINE_POLICIES; do
  HAS_EVENTS=$(aws iam get-role-policy --role-name $ROLE_NAME --policy-name "$policy" --profile $PROFILE \
    --query 'PolicyDocument' --output json | grep -c 'events:PutRule')

  if [ "$HAS_EVENTS" -gt 0 ]; then
    echo "✅ EventBridge 권한 발견: $policy"

    # Condition 확인
    HAS_CONDITION=$(aws iam get-role-policy --role-name $ROLE_NAME --policy-name "$policy" --profile $PROFILE \
      --query 'PolicyDocument' --output json | grep -c 'events:ManagedBy')

    if [ "$HAS_CONDITION" -gt 0 ]; then
      echo "   ✅ Condition (events:ManagedBy) 포함됨"
    else
      echo "   ❌ Condition (events:ManagedBy) 없음 - 문제!"
    fi

    # Resource 확인
    RESOURCE=$(aws iam get-role-policy --role-name $ROLE_NAME --policy-name "$policy" --profile $PROFILE \
      --query 'PolicyDocument.Statement[?Action[0]==`events:PutRule` || contains(Action, `events:PutRule`)].Resource' \
      --output text 2>/dev/null)

    if [ "$RESOURCE" = "*" ]; then
      echo "   ✅ Resource: * (정상)"
    else
      echo "   ⚠️  Resource: $RESOURCE (제한적일 수 있음)"
    fi
  fi
done

echo -e "\n7️⃣  최근 Role 업데이트 시간"
echo "----------------------------------------"
CREATE_DATE=$(aws iam get-role --role-name $ROLE_NAME --profile $PROFILE \
  --query 'Role.CreateDate' --output text)
echo "Role 생성 시간: $CREATE_DATE"

echo -e "\n8️⃣  환경 변수 확인"
echo "----------------------------------------"
echo "DEFAULT_DEST_SFN_ROLE = ${DEFAULT_DEST_SFN_ROLE:-'(설정 안됨)'}"

EXPECTED_ARN="arn:aws:iam::846697434179:role/$ROLE_NAME"
if [ "$DEFAULT_DEST_SFN_ROLE" = "$EXPECTED_ARN" ]; then
  echo "✅ 환경 변수가 올바른 Role ARN을 가리킴"
else
  echo "⚠️  환경 변수가 다른 Role을 가리킬 수 있음"
  echo "   예상: $EXPECTED_ARN"
  echo "   실제: $DEFAULT_DEST_SFN_ROLE"
fi

echo -e "\n========================================"
echo "진단 완료!"
echo "========================================"
echo ""
echo "📋 체크리스트:"
echo "  [ ] Trust Relationship에 states.amazonaws.com 포함"
echo "  [ ] EventBridge 권한에 Condition 포함"
echo "  [ ] EventBridge 권한의 Resource = '*'"
echo "  [ ] Deny Statement 없음"
echo "  [ ] Permission Boundary 없음 또는 제한 없음"
echo "  [ ] 환경 변수가 올바른 Role 가리킴"
echo ""
echo "💡 모든 항목이 체크되었는데도 오류가 발생한다면:"
echo "   1. IAM 정책 변경 후 10분 정도 대기"
echo "   2. CloudTrail 로그 확인"
echo "   3. AWS Support 문의"
