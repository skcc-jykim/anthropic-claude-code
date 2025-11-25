#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ECR (Elastic Container Registry) 리포지토리 및 이미지 마이그레이션 스크립트

기능:
- ECR 리포지토리 생성/복제
- 이미지 태그 마이그레이션
- 리포지토리 설정 복제 (스캔 설정, 암호화 등)
- 리포지토리 정책 및 라이프사이클 정책 복제

사용법:
    export SRC_PROFILE=src
    export DST_PROFILE=dst
    export AWS_REGION=ap-northeast-2
    python migrate_ecr.py

환경 변수:
    SRC_PROFILE: 소스 AWS 프로파일 (기본값: src)
    DST_PROFILE: 대상 AWS 프로파일 (기본값: dst)
    AWS_REGION: AWS 리전 (기본값: ap-northeast-2)
    NAME_PREFIX: 리포지토리 이름 접두사 필터 (선택)
    ECR_REPOSITORIES: 마이그레이션할 리포지토리 목록 (쉼표 구분)
    ECR_REPOSITORIES_FILE: 리포지토리 목록 파일 경로
    MAX_IMAGES_PER_REPO: 리포지토리당 최대 이미지 수 (기본값: 10)
    ECR_IMAGE_TIMEOUT: 이미지 Pull/Push 타임아웃 초 (기본값: 1800 = 30분)
"""

import os
import sys
import subprocess
import logging
import time
import base64
from typing import Optional, List, Dict, Set
import boto3
from botocore.exceptions import ClientError

# ===================================================
# 로깅 설정
# ===================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ===================================================
# 설정
# ===================================================
SRC_PROFILE = os.getenv("SRC_PROFILE", "src")
DST_PROFILE = os.getenv("DST_PROFILE", "dst")
REGION = os.getenv("AWS_REGION", "ap-northeast-2")
NAME_PREFIX = os.getenv("NAME_PREFIX", "")

# ECR 선택적 마이그레이션 설정
ECR_REPOSITORIES = os.getenv("ECR_REPOSITORIES", "")  # 쉼표로 구분된 리포지토리 이름
ECR_REPOSITORIES_FILE = os.getenv("ECR_REPOSITORIES_FILE", "")  # 리포지토리 목록 파일
MAX_IMAGES_PER_REPO = int(os.getenv("MAX_IMAGES_PER_REPO", "10"))  # 리포지토리당 최대 이미지 수
ECR_IMAGE_TIMEOUT = int(os.getenv("ECR_IMAGE_TIMEOUT", "1800"))  # 이미지 Pull/Push 타임아웃 (초, 기본값: 30분)

# 재시도 설정
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

# 통계
stats = {
    "repositories_created": 0,
    "repositories_skipped": 0,
    "images_migrated": 0,
    "images_failed": 0,
    "policies_migrated": 0
}


# ===================================================
# 유틸 함수
# ===================================================

def retry_on_throttle(func):
    """API throttling 시 재시도 데코레이터"""
    def wrapper(*args, **kwargs):
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except ClientError as e:
                error_code = e.response['Error']['Code']
                if error_code in ['TooManyRequestsException', 'ThrottlingException', 'RequestLimitExceeded']:
                    if attempt < MAX_RETRIES - 1:
                        wait_time = RETRY_DELAY * (2 ** attempt)
                        logger.warning(f"Throttled. Retrying in {wait_time}s... (attempt {attempt + 1}/{MAX_RETRIES})")
                        time.sleep(wait_time)
                    else:
                        raise
                else:
                    raise
    return wrapper


def load_repository_list() -> Optional[Set[str]]:
    """ECR 리포지토리 목록 로드 (파일 또는 환경 변수에서)"""
    repositories = set()

    # 1. 파일에서 로드
    if ECR_REPOSITORIES_FILE:
        try:
            with open(ECR_REPOSITORIES_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # 빈 줄이나 주석(#으로 시작) 무시
                    if line and not line.startswith('#'):
                        repositories.add(line)
            logger.info(f"📋 파일에서 {len(repositories)}개의 ECR 리포지토리 목록 로드: {ECR_REPOSITORIES_FILE}")
            return repositories
        except FileNotFoundError:
            logger.error(f"❌ ECR 리포지토리 목록 파일을 찾을 수 없습니다: {ECR_REPOSITORIES_FILE}")
            return None
        except Exception as e:
            logger.error(f"❌ ECR 리포지토리 목록 파일 읽기 실패: {e}")
            return None

    # 2. 환경 변수에서 로드
    if ECR_REPOSITORIES:
        repos = [r.strip() for r in ECR_REPOSITORIES.split(',')]
        repositories = set(r for r in repos if r)
        logger.info(f"📋 환경 변수에서 {len(repositories)}개의 ECR 리포지토리 목록 로드")
        return repositories

    # 둘 다 설정되지 않은 경우
    return None


def should_migrate_repository(repo_name: str, allowed_repos: Optional[Set[str]] = None) -> bool:
    """ECR 리포지토리를 마이그레이션해야 하는지 판단"""

    # 1. NAME_PREFIX 필터
    if NAME_PREFIX and not repo_name.startswith(NAME_PREFIX):
        return False

    # 2. 허용 목록 필터
    if allowed_repos is not None:
        if repo_name not in allowed_repos:
            return False

    return True


def get_ecr_login_password(ecr_client, registry_id: str) -> str:
    """ECR 로그인 비밀번호 가져오기"""
    response = ecr_client.get_authorization_token(registryIds=[registry_id])
    auth_data = response['authorizationData'][0]

    token = base64.b64decode(auth_data['authorizationToken']).decode('utf-8')
    username, password = token.split(':')

    return password


def docker_login(ecr_client, registry_id: str, region: str):
    """Docker를 ECR에 로그인"""
    password = get_ecr_login_password(ecr_client, registry_id)
    endpoint = f"{registry_id}.dkr.ecr.{region}.amazonaws.com"

    result = subprocess.run(
        ['docker', 'login', '--username', 'AWS', '--password-stdin', endpoint],
        input=password.encode(),
        capture_output=True,
        check=True
    )

    return endpoint


# ===================================================
# ECR 리포지토리 마이그레이션
# ===================================================

@retry_on_throttle
def create_repository(ecr_client, repo_name: str, src_repo_config: Dict) -> str:
    """ECR 리포지토리 생성"""
    try:
        # 리포지토리가 이미 존재하는지 확인
        response = ecr_client.describe_repositories(repositoryNames=[repo_name])
        repo_uri = response['repositories'][0]['repositoryUri']
        logger.info(f"  ✔ 리포지토리 이미 존재: {repo_uri}")
        return repo_uri
    except ClientError as e:
        if e.response['Error']['Code'] != 'RepositoryNotFoundException':
            raise

    # 리포지토리 생성
    logger.info(f"  리포지토리 생성 중: {repo_name}")

    create_params = {
        "repositoryName": repo_name
    }

    # 이미지 스캔 설정 복제
    if src_repo_config.get('imageScanningConfiguration'):
        create_params['imageScanningConfiguration'] = src_repo_config['imageScanningConfiguration']

    # 암호화 설정 복제
    if src_repo_config.get('encryptionConfiguration'):
        create_params['encryptionConfiguration'] = src_repo_config['encryptionConfiguration']

    # 이미지 태그 불변성 설정
    if src_repo_config.get('imageTagMutability'):
        create_params['imageTagMutability'] = src_repo_config['imageTagMutability']

    response = ecr_client.create_repository(**create_params)
    repo_uri = response['repository']['repositoryUri']

    logger.info(f"  ✔ 리포지토리 생성 완료: {repo_uri}")
    stats["repositories_created"] += 1

    return repo_uri


@retry_on_throttle
def migrate_repository_policy(src_ecr, dst_ecr, repo_name: str, src_account: str, dst_account: str):
    """리포지토리 정책 마이그레이션"""
    try:
        # 소스 정책 가져오기
        response = src_ecr.get_repository_policy(repositoryName=repo_name)
        policy_text = response['policyText']

        # 계정 ID 교체
        policy_text = policy_text.replace(src_account, dst_account)

        # 대상에 정책 설정
        dst_ecr.set_repository_policy(
            repositoryName=repo_name,
            policyText=policy_text
        )

        logger.info(f"  ✔ 리포지토리 정책 복제 완료")
        stats["policies_migrated"] += 1

    except ClientError as e:
        if e.response['Error']['Code'] == 'RepositoryPolicyNotFoundException':
            logger.info(f"  ℹ️  소스에 리포지토리 정책 없음")
        else:
            logger.warning(f"  ⚠️  리포지토리 정책 복제 실패: {e}")


@retry_on_throttle
def migrate_lifecycle_policy(src_ecr, dst_ecr, repo_name: str):
    """라이프사이클 정책 마이그레이션"""
    try:
        # 소스 정책 가져오기
        response = src_ecr.get_lifecycle_policy(repositoryName=repo_name)
        lifecycle_policy = response['lifecyclePolicyText']

        # 대상에 정책 설정
        dst_ecr.put_lifecycle_policy(
            repositoryName=repo_name,
            lifecyclePolicyText=lifecycle_policy
        )

        logger.info(f"  ✔ 라이프사이클 정책 복제 완료")

    except ClientError as e:
        if e.response['Error']['Code'] == 'LifecyclePolicyNotFoundException':
            logger.info(f"  ℹ️  소스에 라이프사이클 정책 없음")
        else:
            logger.warning(f"  ⚠️  라이프사이클 정책 복제 실패: {e}")


@retry_on_throttle
def get_image_tags(ecr_client, repo_name: str, max_images: int = MAX_IMAGES_PER_REPO) -> List[str]:
    """리포지토리의 이미지 태그 목록 가져오기"""
    tags = []

    try:
        paginator = ecr_client.get_paginator('list_images')
        page_iterator = paginator.paginate(
            repositoryName=repo_name,
            filter={'tagStatus': 'TAGGED'}
        )

        for page in page_iterator:
            for image in page.get('imageIds', []):
                if 'imageTag' in image:
                    tags.append(image['imageTag'])
                    if len(tags) >= max_images:
                        logger.info(f"  ℹ️  최대 이미지 수({max_images})에 도달")
                        return tags

    except ClientError as e:
        logger.warning(f"  ⚠️  이미지 태그 목록 가져오기 실패: {e}")

    return tags


def migrate_image(
    src_image_uri: str,
    dst_image_uri: str,
    src_endpoint: str,
    dst_endpoint: str
) -> bool:
    """Docker를 사용하여 이미지 마이그레이션"""
    try:
        # 이미지 Pull
        logger.info(f"    Pull: {src_image_uri} (타임아웃: {ECR_IMAGE_TIMEOUT}초)")
        result = subprocess.run(
            ['docker', 'pull', src_image_uri],
            capture_output=True,
            check=True,
            timeout=ECR_IMAGE_TIMEOUT
        )

        # 이미지 태그
        logger.info(f"    Tag: {dst_image_uri}")
        subprocess.run(
            ['docker', 'tag', src_image_uri, dst_image_uri],
            capture_output=True,
            check=True
        )

        # 이미지 Push
        logger.info(f"    Push: {dst_image_uri} (타임아웃: {ECR_IMAGE_TIMEOUT}초)")
        subprocess.run(
            ['docker', 'push', dst_image_uri],
            capture_output=True,
            check=True,
            timeout=ECR_IMAGE_TIMEOUT
        )

        # 로컬 이미지 정리
        try:
            subprocess.run(['docker', 'rmi', src_image_uri], capture_output=True, check=False)
            subprocess.run(['docker', 'rmi', dst_image_uri], capture_output=True, check=False)
        except Exception:
            pass

        logger.info(f"    ✔ 이미지 마이그레이션 완료: {dst_image_uri}")
        stats["images_migrated"] += 1
        return True

    except subprocess.TimeoutExpired:
        logger.error(f"    ❌ 타임아웃: {src_image_uri}")
        stats["images_failed"] += 1
        return False
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"    ❌ Docker 명령 실패: {error_msg}")
        stats["images_failed"] += 1
        return False
    except Exception as e:
        logger.error(f"    ❌ 이미지 마이그레이션 실패: {e}")
        stats["images_failed"] += 1
        return False


@retry_on_throttle
def migrate_repository(
    src_ecr,
    dst_ecr,
    repo_name: str,
    src_account: str,
    dst_account: str,
    src_endpoint: str,
    dst_endpoint: str,
    region: str
):
    """ECR 리포지토리 마이그레이션 (설정, 정책, 이미지 포함)"""

    logger.info(f"\n{'='*50}")
    logger.info(f"🔄 리포지토리 마이그레이션: {repo_name}")
    logger.info(f"{'='*50}")

    try:
        # 1. 소스 리포지토리 정보 가져오기
        src_repo_response = src_ecr.describe_repositories(repositoryNames=[repo_name])
        src_repo = src_repo_response['repositories'][0]

        # 2. 대상 리포지토리 생성
        dst_repo_uri = create_repository(dst_ecr, repo_name, src_repo)

        # 3. 리포지토리 정책 복제
        migrate_repository_policy(src_ecr, dst_ecr, repo_name, src_account, dst_account)

        # 4. 라이프사이클 정책 복제
        migrate_lifecycle_policy(src_ecr, dst_ecr, repo_name)

        # 5. 이미지 태그 목록 가져오기
        image_tags = get_image_tags(src_ecr, repo_name, MAX_IMAGES_PER_REPO)

        if not image_tags:
            logger.info(f"  ℹ️  마이그레이션할 이미지가 없습니다")
            return

        logger.info(f"  📦 {len(image_tags)}개의 이미지 마이그레이션 시작")

        # 6. 각 이미지 마이그레이션
        for tag in image_tags:
            src_image_uri = f"{src_endpoint}/{repo_name}:{tag}"
            dst_image_uri = f"{dst_endpoint}/{repo_name}:{tag}"

            logger.info(f"  🔄 이미지 태그: {tag}")
            migrate_image(src_image_uri, dst_image_uri, src_endpoint, dst_endpoint)

        logger.info(f"  ✔ 리포지토리 마이그레이션 완료: {repo_name}")

    except ClientError as e:
        if e.response['Error']['Code'] == 'RepositoryNotFoundException':
            logger.error(f"  ❌ 소스 리포지토리를 찾을 수 없음: {repo_name}")
        else:
            logger.error(f"  ❌ 리포지토리 마이그레이션 실패: {e}")
        stats["repositories_skipped"] += 1
    except Exception as e:
        logger.error(f"  ❌ 리포지토리 마이그레이션 실패: {e}")
        stats["repositories_skipped"] += 1


# ===================================================
# 메인 실행
# ===================================================

def main():
    logger.info("\n" + "="*70)
    logger.info("🐳 ECR 리포지토리 마이그레이션 시작")
    logger.info("="*70)
    logger.info(f"소스 프로파일: {SRC_PROFILE}")
    logger.info(f"대상 프로파일: {DST_PROFILE}")
    logger.info(f"리전: {REGION}")
    logger.info(f"이름 접두사 필터: {NAME_PREFIX if NAME_PREFIX else '(전체)'}")
    logger.info(f"리포지토리당 최대 이미지: {MAX_IMAGES_PER_REPO}개")
    logger.info(f"이미지 Pull/Push 타임아웃: {ECR_IMAGE_TIMEOUT}초 ({ECR_IMAGE_TIMEOUT // 60}분)")
    logger.info("="*70)

    # Docker 설치 확인
    try:
        subprocess.run(['docker', '--version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.error("❌ Docker가 설치되어 있지 않거나 실행할 수 없습니다!")
        logger.error("   Docker를 설치하고 Docker daemon이 실행 중인지 확인하세요.")
        return 1

    # 세션 생성
    src_sess = boto3.Session(profile_name=SRC_PROFILE, region_name=REGION)
    dst_sess = boto3.Session(profile_name=DST_PROFILE, region_name=REGION)

    # 계정 ID 추출
    src_sts = src_sess.client("sts")
    dst_sts = dst_sess.client("sts")
    src_account = src_sts.get_caller_identity()["Account"]
    dst_account = dst_sts.get_caller_identity()["Account"]

    logger.info(f"소스 계정: {src_account}")
    logger.info(f"대상 계정: {dst_account}")

    # ECR 클라이언트 생성
    src_ecr = src_sess.client("ecr")
    dst_ecr = dst_sess.client("ecr")

    # Docker 로그인
    logger.info("\n🔐 ECR 로그인 중...")
    try:
        src_endpoint = docker_login(src_ecr, src_account, REGION)
        logger.info(f"  ✔ 소스 ECR 로그인 완료: {src_endpoint}")

        dst_endpoint = docker_login(dst_ecr, dst_account, REGION)
        logger.info(f"  ✔ 대상 ECR 로그인 완료: {dst_endpoint}")
    except Exception as e:
        logger.error(f"❌ ECR 로그인 실패: {e}")
        return 1

    # 리포지토리 목록 로드
    allowed_repos = load_repository_list()
    if allowed_repos is not None:
        logger.info(f"\n✅ 선택적 마이그레이션 모드: {len(allowed_repos)}개의 리포지토리만 이관합니다")
        logger.info(f"📝 대상 리포지토리: {', '.join(sorted(allowed_repos))}")

    # 리포지토리 목록 가져오기
    logger.info("\n📋 리포지토리 목록 조회 중...")

    try:
        paginator = src_ecr.get_paginator('describe_repositories')
        page_iterator = paginator.paginate()

        repo_count = 0
        for page in page_iterator:
            for repo in page.get('repositories', []):
                repo_name = repo['repositoryName']

                # 필터링
                if not should_migrate_repository(repo_name, allowed_repos):
                    logger.debug(f"  ⏭️  스킵: {repo_name}")
                    continue

                repo_count += 1

                # 리포지토리 마이그레이션
                migrate_repository(
                    src_ecr,
                    dst_ecr,
                    repo_name,
                    src_account,
                    dst_account,
                    src_endpoint,
                    dst_endpoint,
                    REGION
                )

        # 최종 통계
        logger.info("\n" + "="*70)
        logger.info("✅ ECR 마이그레이션 완료!")
        logger.info("="*70)
        logger.info(f"📊 통계:")
        logger.info(f"  🏗️  생성된 리포지토리: {stats['repositories_created']}개")
        logger.info(f"  ⏭️  스킵된 리포지토리: {stats['repositories_skipped']}개")
        logger.info(f"  🐳 마이그레이션된 이미지: {stats['images_migrated']}개")
        logger.info(f"  ❌ 실패한 이미지: {stats['images_failed']}개")
        logger.info(f"  📋 복제된 정책: {stats['policies_migrated']}개")
        logger.info("="*70)

        return 0 if stats['images_failed'] == 0 else 1

    except Exception as e:
        logger.error(f"\n❌ 마이그레이션 중 치명적 오류 발생: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
