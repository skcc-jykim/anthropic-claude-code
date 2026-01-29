#!/usr/bin/env python3
"""
AWS Lambda function for querying S3 Table Bucket data using Athena SDK.

S3 Table Bucket은 Apache Iceberg 테이블 형식을 사용하며,
Athena를 통해 SQL 쿼리로 데이터에 접근할 수 있습니다.

Environment Variables:
    - ATHENA_DATABASE: Athena 데이터베이스 이름
    - ATHENA_WORKGROUP: Athena 워크그룹 (기본값: primary)
    - ATHENA_OUTPUT_LOCATION: 쿼리 결과 저장 S3 위치
    - QUERY_TIMEOUT_SECONDS: 쿼리 타임아웃 (기본값: 300)
    - AWS_REGION: AWS 리전 (기본값: ap-northeast-2)
    - AWS_PROFILE: AWS 프로파일 (로컬 실행 시 사용)
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Union

import boto3
from botocore.exceptions import ClientError

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 환경 변수
ATHENA_DATABASE = os.getenv("ATHENA_DATABASE", "default")
ATHENA_WORKGROUP = os.getenv("ATHENA_WORKGROUP", "primary")
ATHENA_OUTPUT_LOCATION = os.getenv("ATHENA_OUTPUT_LOCATION", "")
QUERY_TIMEOUT_SECONDS = int(os.getenv("QUERY_TIMEOUT_SECONDS", "300"))
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-2")
AWS_PROFILE = os.getenv("AWS_PROFILE", None)

# boto3 세션 (로컬 실행 시 profile 사용)
_session: Optional[boto3.Session] = None

# Athena 쿼리 상태
QUERY_STATE_SUCCEEDED = "SUCCEEDED"
QUERY_STATE_FAILED = "FAILED"
QUERY_STATE_CANCELLED = "CANCELLED"
QUERY_TERMINAL_STATES = {QUERY_STATE_SUCCEEDED, QUERY_STATE_FAILED, QUERY_STATE_CANCELLED}


class AthenaQueryError(Exception):
    """Athena 쿼리 실행 중 발생하는 에러"""
    pass


class AthenaQueryTimeout(Exception):
    """Athena 쿼리 타임아웃 에러"""
    pass


def get_session(profile_name: Optional[str] = None) -> boto3.Session:
    """
    boto3 세션을 반환합니다.

    Args:
        profile_name: AWS 프로파일 이름 (로컬 실행 시 사용)

    Returns:
        boto3 세션
    """
    global _session

    profile = profile_name or AWS_PROFILE

    if _session is None:
        if profile:
            logger.info(f"AWS 프로파일 사용: {profile}")
            _session = boto3.Session(profile_name=profile, region_name=AWS_REGION)
        else:
            _session = boto3.Session(region_name=AWS_REGION)

    return _session


def set_profile(profile_name: str) -> None:
    """
    AWS 프로파일을 설정합니다 (로컬 실행 시 사용).

    Args:
        profile_name: AWS 프로파일 이름
    """
    global _session, AWS_PROFILE
    AWS_PROFILE = profile_name
    _session = None  # 세션 재생성을 위해 초기화
    logger.info(f"AWS 프로파일 설정: {profile_name}")


def get_athena_client(profile_name: Optional[str] = None):
    """
    Athena 클라이언트 생성

    Args:
        profile_name: AWS 프로파일 이름 (로컬 실행 시 사용)
    """
    session = get_session(profile_name)
    return session.client("athena", region_name=AWS_REGION)


def start_query_execution(
    athena_client,
    query: str,
    database: Optional[str] = None,
    catalog: Optional[str] = None,
    workgroup: Optional[str] = None,
    output_location: Optional[str] = None
) -> str:
    """
    Athena 쿼리 실행을 시작합니다.

    Args:
        athena_client: Athena boto3 클라이언트
        query: 실행할 SQL 쿼리
        database: 데이터베이스 이름 (기본값: 환경 변수)
        catalog: 데이터 카탈로그 이름 (S3 Table Bucket의 경우 테이블 버킷 ARN 사용)
        workgroup: Athena 워크그룹 (기본값: 환경 변수)
        output_location: 결과 저장 S3 위치 (기본값: 환경 변수)

    Returns:
        쿼리 실행 ID

    Raises:
        AthenaQueryError: 쿼리 시작 실패 시
    """
    database = database or ATHENA_DATABASE
    workgroup = workgroup or ATHENA_WORKGROUP
    output_location = output_location or ATHENA_OUTPUT_LOCATION

    query_context = {"Database": database}
    if catalog:
        query_context["Catalog"] = catalog

    params = {
        "QueryString": query,
        "QueryExecutionContext": query_context,
        "WorkGroup": workgroup
    }

    # 워크그룹에 출력 위치가 설정되어 있지 않은 경우에만 지정
    if output_location:
        params["ResultConfiguration"] = {
            "OutputLocation": output_location
        }

    try:
        response = athena_client.start_query_execution(**params)
        query_execution_id = response["QueryExecutionId"]
        logger.info(f"쿼리 실행 시작 - ID: {query_execution_id}")
        return query_execution_id
    except ClientError as e:
        error_msg = f"쿼리 실행 시작 실패: {e.response['Error']['Message']}"
        logger.error(f"❌ {error_msg}")
        raise AthenaQueryError(error_msg) from e


def wait_for_query_completion(
    athena_client,
    query_execution_id: str,
    timeout_seconds: Optional[int] = None,
    poll_interval: float = 1.0
) -> Dict[str, Any]:
    """
    쿼리 완료를 대기합니다.

    Args:
        athena_client: Athena boto3 클라이언트
        query_execution_id: 쿼리 실행 ID
        timeout_seconds: 타임아웃 (초) (기본값: 환경 변수)
        poll_interval: 폴링 간격 (초)

    Returns:
        쿼리 실행 정보

    Raises:
        AthenaQueryTimeout: 타임아웃 발생 시
        AthenaQueryError: 쿼리 실패 시
    """
    timeout_seconds = timeout_seconds or QUERY_TIMEOUT_SECONDS
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            # 타임아웃 시 쿼리 취소
            try:
                athena_client.stop_query_execution(QueryExecutionId=query_execution_id)
                logger.warning(f"⚠️ 쿼리 타임아웃으로 취소됨 - ID: {query_execution_id}")
            except ClientError:
                pass
            raise AthenaQueryTimeout(
                f"쿼리 타임아웃 ({timeout_seconds}초) - ID: {query_execution_id}"
            )

        try:
            response = athena_client.get_query_execution(
                QueryExecutionId=query_execution_id
            )
            query_execution = response["QueryExecution"]
            state = query_execution["Status"]["State"]

            if state in QUERY_TERMINAL_STATES:
                if state == QUERY_STATE_SUCCEEDED:
                    logger.info(f"✅ 쿼리 성공 - ID: {query_execution_id}")
                    return query_execution
                elif state == QUERY_STATE_FAILED:
                    reason = query_execution["Status"].get(
                        "StateChangeReason", "알 수 없는 오류"
                    )
                    logger.error(f"❌ 쿼리 실패 - ID: {query_execution_id}, 원인: {reason}")
                    raise AthenaQueryError(f"쿼리 실패: {reason}")
                else:  # CANCELLED
                    logger.warning(f"⚠️ 쿼리 취소됨 - ID: {query_execution_id}")
                    raise AthenaQueryError("쿼리가 취소되었습니다")

            logger.debug(f"쿼리 진행 중... 상태: {state}, 경과: {elapsed:.1f}초")
            time.sleep(poll_interval)

        except ClientError as e:
            error_msg = f"쿼리 상태 확인 실패: {e.response['Error']['Message']}"
            logger.error(f"❌ {error_msg}")
            raise AthenaQueryError(error_msg) from e


def get_query_results(
    athena_client,
    query_execution_id: str,
    max_results: int = 1000,
    include_header: bool = True
) -> List[List[str]]:
    """
    쿼리 결과를 가져옵니다.

    Args:
        athena_client: Athena boto3 클라이언트
        query_execution_id: 쿼리 실행 ID
        max_results: 최대 결과 수 (기본값: 1000)
        include_header: 헤더 포함 여부

    Returns:
        결과 행 리스트 (각 행은 컬럼 값 리스트)
    """
    results = []
    next_token = None
    first_page = True

    try:
        while True:
            params = {
                "QueryExecutionId": query_execution_id,
                "MaxResults": min(max_results, 1000)
            }
            if next_token:
                params["NextToken"] = next_token

            response = athena_client.get_query_results(**params)
            rows = response["ResultSet"]["Rows"]

            for i, row in enumerate(rows):
                # 첫 페이지의 첫 행은 헤더
                if first_page and i == 0:
                    if include_header:
                        results.append([col.get("VarCharValue", "") for col in row["Data"]])
                    first_page = False
                    continue

                results.append([col.get("VarCharValue", "") for col in row["Data"]])

            next_token = response.get("NextToken")
            if not next_token or len(results) >= max_results:
                break

        logger.info(f"쿼리 결과 조회 완료 - 행 수: {len(results)}")
        return results

    except ClientError as e:
        error_msg = f"쿼리 결과 조회 실패: {e.response['Error']['Message']}"
        logger.error(f"❌ {error_msg}")
        raise AthenaQueryError(error_msg) from e


def get_query_results_as_dict(
    athena_client,
    query_execution_id: str,
    max_results: int = 1000
) -> List[Dict[str, str]]:
    """
    쿼리 결과를 딕셔너리 리스트로 반환합니다.

    Args:
        athena_client: Athena boto3 클라이언트
        query_execution_id: 쿼리 실행 ID
        max_results: 최대 결과 수

    Returns:
        딕셔너리 리스트 (각 딕셔너리는 컬럼명: 값 형태)
    """
    rows = get_query_results(athena_client, query_execution_id, max_results, include_header=True)

    if not rows:
        return []

    headers = rows[0]
    result_dicts = []

    for row in rows[1:]:
        row_dict = {}
        for i, value in enumerate(row):
            if i < len(headers):
                row_dict[headers[i]] = value
        result_dicts.append(row_dict)

    return result_dicts


def execute_query(
    query: str,
    database: Optional[str] = None,
    catalog: Optional[str] = None,
    workgroup: Optional[str] = None,
    output_location: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    return_as_dict: bool = True
) -> Union[List[Dict[str, str]], List[List[str]]]:
    """
    Athena 쿼리를 실행하고 결과를 반환하는 통합 함수.

    Args:
        query: 실행할 SQL 쿼리
        database: 데이터베이스 이름
        catalog: 데이터 카탈로그 (S3 Table Bucket ARN)
        workgroup: Athena 워크그룹
        output_location: 결과 저장 S3 위치
        timeout_seconds: 타임아웃 (초)
        return_as_dict: True면 딕셔너리 리스트, False면 리스트 리스트 반환

    Returns:
        쿼리 결과

    Example:
        # S3 Table Bucket 쿼리
        results = execute_query(
            query="SELECT * FROM my_table LIMIT 10",
            database="my_database",
            catalog="arn:aws:s3tables:ap-northeast-2:123456789012:bucket/my-table-bucket"
        )
    """
    athena_client = get_athena_client()

    # 쿼리 실행
    query_execution_id = start_query_execution(
        athena_client=athena_client,
        query=query,
        database=database,
        catalog=catalog,
        workgroup=workgroup,
        output_location=output_location
    )

    # 완료 대기
    wait_for_query_completion(
        athena_client=athena_client,
        query_execution_id=query_execution_id,
        timeout_seconds=timeout_seconds
    )

    # 결과 조회
    if return_as_dict:
        return get_query_results_as_dict(athena_client, query_execution_id)
    else:
        return get_query_results(athena_client, query_execution_id)


def query_s3_table_bucket(
    table_bucket_arn: str,
    namespace: str,
    table_name: str,
    query: Optional[str] = None,
    columns: Optional[List[str]] = None,
    where_clause: Optional[str] = None,
    limit: Optional[int] = None,
    timeout_seconds: Optional[int] = None
) -> List[Dict[str, str]]:
    """
    S3 Table Bucket의 테이블을 쿼리합니다.

    S3 Table Bucket은 Apache Iceberg 형식의 테이블을 저장하며,
    Athena를 통해 SQL로 쿼리할 수 있습니다.

    Args:
        table_bucket_arn: S3 Table Bucket ARN
            예: arn:aws:s3tables:ap-northeast-2:123456789012:bucket/my-table-bucket
        namespace: 네임스페이스 (데이터베이스)
        table_name: 테이블 이름
        query: 커스텀 SQL 쿼리 (지정 시 다른 파라미터 무시)
        columns: 조회할 컬럼 리스트 (None이면 *)
        where_clause: WHERE 조건절 (WHERE 키워드 제외)
        limit: 결과 제한 수
        timeout_seconds: 쿼리 타임아웃 (초)

    Returns:
        쿼리 결과 딕셔너리 리스트

    Example:
        # 전체 데이터 조회
        results = query_s3_table_bucket(
            table_bucket_arn="arn:aws:s3tables:ap-northeast-2:123456789012:bucket/my-bucket",
            namespace="my_namespace",
            table_name="my_table",
            limit=100
        )

        # 특정 컬럼과 조건으로 조회
        results = query_s3_table_bucket(
            table_bucket_arn="arn:aws:s3tables:ap-northeast-2:123456789012:bucket/my-bucket",
            namespace="my_namespace",
            table_name="my_table",
            columns=["id", "name", "created_at"],
            where_clause="created_at >= '2024-01-01'",
            limit=1000
        )
    """
    if query:
        sql = query
    else:
        # SELECT 절 구성
        select_cols = ", ".join(columns) if columns else "*"

        # 전체 테이블 참조 (namespace.table_name)
        table_ref = f'"{namespace}"."{table_name}"'

        sql = f"SELECT {select_cols} FROM {table_ref}"

        if where_clause:
            sql += f" WHERE {where_clause}"

        if limit:
            sql += f" LIMIT {limit}"

    logger.info(f"S3 Table Bucket 쿼리 실행: {sql[:200]}...")

    return execute_query(
        query=sql,
        database=namespace,
        catalog=table_bucket_arn,
        timeout_seconds=timeout_seconds
    )


def list_s3_table_namespaces(table_bucket_arn: str) -> List[str]:
    """
    S3 Table Bucket의 네임스페이스 목록을 조회합니다.

    Args:
        table_bucket_arn: S3 Table Bucket ARN

    Returns:
        네임스페이스 이름 리스트
    """
    query = "SHOW DATABASES"
    results = execute_query(
        query=query,
        catalog=table_bucket_arn,
        return_as_dict=False
    )

    # 첫 번째 열이 데이터베이스/네임스페이스 이름
    return [row[0] for row in results if row]


def list_s3_table_tables(table_bucket_arn: str, namespace: str) -> List[str]:
    """
    S3 Table Bucket의 특정 네임스페이스에 있는 테이블 목록을 조회합니다.

    Args:
        table_bucket_arn: S3 Table Bucket ARN
        namespace: 네임스페이스 이름

    Returns:
        테이블 이름 리스트
    """
    query = f'SHOW TABLES IN "{namespace}"'
    results = execute_query(
        query=query,
        database=namespace,
        catalog=table_bucket_arn,
        return_as_dict=False
    )

    return [row[0] for row in results if row]


def describe_s3_table(
    table_bucket_arn: str,
    namespace: str,
    table_name: str
) -> List[Dict[str, str]]:
    """
    S3 Table Bucket 테이블의 스키마를 조회합니다.

    Args:
        table_bucket_arn: S3 Table Bucket ARN
        namespace: 네임스페이스 이름
        table_name: 테이블 이름

    Returns:
        컬럼 정보 리스트 (컬럼명, 데이터타입, 설명 등)
    """
    query = f'DESCRIBE "{namespace}"."{table_name}"'
    return execute_query(
        query=query,
        database=namespace,
        catalog=table_bucket_arn
    )


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda 핸들러 함수.

    Event 구조:
        {
            "action": "query" | "list_namespaces" | "list_tables" | "describe",
            "table_bucket_arn": "arn:aws:s3tables:...",
            "namespace": "my_namespace",  # query, list_tables, describe에 필요
            "table_name": "my_table",     # query, describe에 필요
            "query": "SELECT ...",         # 선택적: 커스텀 쿼리
            "columns": ["col1", "col2"],   # 선택적: 조회할 컬럼
            "where_clause": "id > 100",    # 선택적: WHERE 조건
            "limit": 100                   # 선택적: 결과 제한
        }

    Returns:
        {
            "statusCode": 200 | 400 | 500,
            "body": { "data": [...] } | { "error": "..." }
        }
    """
    logger.info(f"Lambda 이벤트 수신: {json.dumps(event, ensure_ascii=False)}")

    try:
        action = event.get("action", "query")
        table_bucket_arn = event.get("table_bucket_arn")

        if not table_bucket_arn:
            return {
                "statusCode": 400,
                "body": {"error": "table_bucket_arn은 필수입니다"}
            }

        if action == "list_namespaces":
            # 네임스페이스 목록 조회
            namespaces = list_s3_table_namespaces(table_bucket_arn)
            return {
                "statusCode": 200,
                "body": {"namespaces": namespaces}
            }

        elif action == "list_tables":
            # 테이블 목록 조회
            namespace = event.get("namespace")
            if not namespace:
                return {
                    "statusCode": 400,
                    "body": {"error": "namespace는 필수입니다"}
                }

            tables = list_s3_table_tables(table_bucket_arn, namespace)
            return {
                "statusCode": 200,
                "body": {"tables": tables}
            }

        elif action == "describe":
            # 테이블 스키마 조회
            namespace = event.get("namespace")
            table_name = event.get("table_name")

            if not namespace or not table_name:
                return {
                    "statusCode": 400,
                    "body": {"error": "namespace와 table_name은 필수입니다"}
                }

            schema = describe_s3_table(table_bucket_arn, namespace, table_name)
            return {
                "statusCode": 200,
                "body": {"schema": schema}
            }

        elif action == "query":
            # 데이터 쿼리
            namespace = event.get("namespace")
            table_name = event.get("table_name")
            custom_query = event.get("query")

            if not custom_query and (not namespace or not table_name):
                return {
                    "statusCode": 400,
                    "body": {"error": "query 또는 namespace와 table_name이 필요합니다"}
                }

            if custom_query:
                # 커스텀 쿼리 실행
                results = execute_query(
                    query=custom_query,
                    database=namespace,
                    catalog=table_bucket_arn,
                    timeout_seconds=event.get("timeout_seconds")
                )
            else:
                # 테이블 쿼리
                results = query_s3_table_bucket(
                    table_bucket_arn=table_bucket_arn,
                    namespace=namespace,
                    table_name=table_name,
                    columns=event.get("columns"),
                    where_clause=event.get("where_clause"),
                    limit=event.get("limit"),
                    timeout_seconds=event.get("timeout_seconds")
                )

            return {
                "statusCode": 200,
                "body": {"data": results, "count": len(results)}
            }

        else:
            return {
                "statusCode": 400,
                "body": {"error": f"지원하지 않는 action: {action}"}
            }

    except AthenaQueryTimeout as e:
        logger.error(f"❌ 쿼리 타임아웃: {e}")
        return {
            "statusCode": 408,
            "body": {"error": str(e)}
        }

    except AthenaQueryError as e:
        logger.error(f"❌ 쿼리 에러: {e}")
        return {
            "statusCode": 500,
            "body": {"error": str(e)}
        }

    except Exception as e:
        logger.exception(f"❌ 예상치 못한 에러: {e}")
        return {
            "statusCode": 500,
            "body": {"error": f"내부 서버 오류: {str(e)}"}
        }


# 로컬 테스트용 CLI
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="S3 Table Bucket 데이터를 Athena로 쿼리합니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # 네임스페이스 목록 조회
  python lambda_athena_s3_table.py --profile my-profile \\
    --action list_namespaces \\
    --table-bucket-arn arn:aws:s3tables:ap-northeast-2:123456789012:bucket/my-bucket

  # 테이블 목록 조회
  python lambda_athena_s3_table.py --profile my-profile \\
    --action list_tables \\
    --table-bucket-arn arn:aws:s3tables:ap-northeast-2:123456789012:bucket/my-bucket \\
    --namespace my_namespace

  # 테이블 스키마 조회
  python lambda_athena_s3_table.py --profile my-profile \\
    --action describe \\
    --table-bucket-arn arn:aws:s3tables:ap-northeast-2:123456789012:bucket/my-bucket \\
    --namespace my_namespace \\
    --table-name my_table

  # 데이터 쿼리
  python lambda_athena_s3_table.py --profile my-profile \\
    --action query \\
    --table-bucket-arn arn:aws:s3tables:ap-northeast-2:123456789012:bucket/my-bucket \\
    --namespace my_namespace \\
    --table-name my_table \\
    --columns id,name,created_at \\
    --where "id > 0" \\
    --limit 10

  # 커스텀 SQL 쿼리
  python lambda_athena_s3_table.py --profile my-profile \\
    --table-bucket-arn arn:aws:s3tables:ap-northeast-2:123456789012:bucket/my-bucket \\
    --namespace my_namespace \\
    --sql "SELECT COUNT(*) FROM my_namespace.my_table"
"""
    )

    # AWS 설정
    parser.add_argument("--profile", "-p", help="AWS 프로파일 이름")
    parser.add_argument("--region", "-r", default="ap-northeast-2", help="AWS 리전 (기본값: ap-northeast-2)")

    # 필수 파라미터
    parser.add_argument("--table-bucket-arn", "-b", required=True, help="S3 Table Bucket ARN")

    # Action 선택
    parser.add_argument(
        "--action", "-a",
        choices=["query", "list_namespaces", "list_tables", "describe"],
        default="query",
        help="수행할 작업 (기본값: query)"
    )

    # 쿼리 파라미터
    parser.add_argument("--namespace", "-n", help="네임스페이스 (데이터베이스)")
    parser.add_argument("--table-name", "-t", help="테이블 이름")
    parser.add_argument("--sql", "-q", help="커스텀 SQL 쿼리")
    parser.add_argument("--columns", "-c", help="조회할 컬럼 (쉼표 구분)")
    parser.add_argument("--where", "-w", help="WHERE 조건절")
    parser.add_argument("--limit", "-l", type=int, help="결과 제한 수")

    # Athena 설정
    parser.add_argument("--workgroup", default="primary", help="Athena 워크그룹 (기본값: primary)")
    parser.add_argument("--output-location", "-o", help="쿼리 결과 S3 위치")
    parser.add_argument("--timeout", type=int, default=300, help="쿼리 타임아웃 초 (기본값: 300)")

    args = parser.parse_args()

    # 전역 변수 선언 (할당 전에 먼저 선언)
    global AWS_REGION, ATHENA_WORKGROUP, ATHENA_OUTPUT_LOCATION

    # 전역 설정 업데이트
    if args.region:
        AWS_REGION = args.region

    # 프로파일 설정
    if args.profile:
        set_profile(args.profile)

    # 이벤트 구성
    event = {
        "action": args.action,
        "table_bucket_arn": args.table_bucket_arn,
    }

    if args.namespace:
        event["namespace"] = args.namespace
    if args.table_name:
        event["table_name"] = args.table_name
    if args.sql:
        event["query"] = args.sql
    if args.columns:
        event["columns"] = [c.strip() for c in args.columns.split(",")]
    if args.where:
        event["where_clause"] = args.where
    if args.limit:
        event["limit"] = args.limit
    if args.timeout:
        event["timeout_seconds"] = args.timeout

    # Athena 워크그룹/출력 위치 설정
    if args.workgroup:
        ATHENA_WORKGROUP = args.workgroup
    if args.output_location:
        ATHENA_OUTPUT_LOCATION = args.output_location

    # 실행
    logger.info(f"이벤트: {json.dumps(event, ensure_ascii=False)}")
    result = lambda_handler(event, None)
    print(json.dumps(result, indent=2, ensure_ascii=False))
