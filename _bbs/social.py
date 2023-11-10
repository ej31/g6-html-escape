import hashlib
import logging
import sys
import zlib
from datetime import datetime
from typing import Optional, List
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.templating import Jinja2Templates

from _bbs.member_profile import validate_nickname, validate_userid
from _lib.social import providers
from _lib.social.social import oauth, SocialProvider, get_social_profile, get_social_login_token
from common import AlertException, valid_email, hash_password, session_member_key, insert_point, TEMPLATES_DIR, \
    is_admin, generate_one_time_token, default_if_none, generate_token
from database import SessionLocal, get_db
from dataclassform import MemberForm

from models import Config, MemberSocialProfiles, Member

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR, extensions=["jinja2.ext.i18n"])
templates.env.globals["is_admin"] = is_admin
templates.env.globals["generate_one_time_token"] = generate_one_time_token
templates.env.filters["default_if_none"] = default_if_none
templates.env.globals['getattr'] = getattr
templates.env.globals["generate_token"] = generate_token

log = logging.getLogger("authlib")
log.addHandler(logging.StreamHandler(sys.stdout))
logging.basicConfig()
log.setLevel(logging.DEBUG)


@router.get('/social/login')
async def social_login(request: Request):
    """
    소셜 로그인
    """
    config: Config = request.state.config
    provider: List = parse_qs(request.url.query).get('provider', [])
    if provider.__len__() == 0:
        raise AlertException(status_code=400, detail="사용하지 않는 서비스 입니다.")

    provider_name = provider[0]

    if provider_name not in config.cf_social_servicelist:
        raise AlertException(status_code=400, detail="사용하지 않는 서비스 입니다. 관리자에게 문의하십시오.")

    # 소셜프로바이더 등록 - 다형성으로 호출
    provider_module_name = getattr(providers, f"{provider_name}")
    provider_class: SocialProvider = getattr(provider_module_name, f"{provider_name.capitalize()}")

    # 변경되는 설정값을 반영하기위해 여기서 client_id, secret 키를 등록한다.
    if provider_name == "naver":
        if not (config.cf_naver_clientid.strip() and config.cf_naver_secret.strip()):
            raise AlertException(status_code=400, detail="사용하지 않는 서비스 입니다. 관리자에게 문의하십시오.")
        provider_class.register(oauth, config.cf_naver_clientid.strip(), config.cf_naver_secret.strip())

    elif provider_name == 'kakao':
        if not config.cf_kakao_rest_key:
            raise AlertException(status_code=400, detail="사용하지 않는 서비스 입니다. 관리자에게 문의하십시오.")

        # 카카오 client_secret 은 선택사항
        provider_class.register(oauth, config.cf_kakao_rest_key.strip(), config.cf_kakao_client_secret.strip())

    elif provider_name == 'google':
        if not (config.cf_google_clientid.strip() and config.cf_google_secret.strip()):
            raise AlertException(status_code=400, detail="사용하지 않는 서비스 입니다. 관리자에게 문의하십시오.")

        provider_class.register(oauth, config.cf_google_clientid.strip(), config.cf_google_secret.strip())

    elif provider_name == 'twitter':
        if not (config.cf_twitter_key.strip() and config.cf_twitter_secret.strip()):
            raise AlertException(status_code=400, detail="사용하지 않는 서비스 입니다. 관리자에게 문의하십시오.")

        provider_class.register(oauth, config.cf_twitter_key.strip(), config.cf_twitter_secret.strip())

    elif provider_name == 'facebook':
        if not (config.cf_facebook_appid.strip() and config.cf_facebook_secret.strip()):
            raise AlertException(status_code=400, detail="사용하지 않는 서비스 입니다. 관리자에게 문의하십시오.")

        provider_class.register(oauth, config.cf_facebook_appid.strip(), config.cf_facebook_secret.strip())

    redirect_uri = f"{request.url_for('authorize_social_login').__str__()}?provider={provider_name}"
    redirect_uri = redirect_uri.replace(":443", "")

    return await oauth.__getattr__(provider_name).authorize_redirect(request, redirect_uri)


@router.get('/social/login/callback')
async def authorize_social_login(request: Request):
    """
    소셜 로그인 인증 콜백
    """
    provider: List = parse_qs(request.url.query).get('provider', [])
    if provider.__len__() == 0:
        raise AlertException(status_code=400, detail="사용하지 않는 서비스 입니다.")
    provider_name: str = provider[0]

    auth_token = await get_social_login_token(provider_name, request)
    if auth_token is None:
        raise AlertException(status_code=400, detail="잠시후에 다시 시도해 주세요.",
                             url=request.url_for('login').__str__())

    social_service = SocialAuthService()

    provider_module_name = getattr(providers, f"{provider_name}")
    provider_class: SocialProvider = getattr(provider_module_name, f"{provider_name.capitalize()}")

    request.session['ss_social_access'] = auth_token
    response = await get_social_profile(auth_token, provider_name, request)

    social_email, profile = provider_class.convert_gnu_profile_data(response)
    identifier = str(profile.identifier)
    if not identifier:
        logging.critical(
            f'social login identifier is empty, gnu profile convert parsing error. '
            f'social_provider: {provider}, profile: {profile}')
        raise AlertException(status_code=400, detail="유효하지 않은 요청입니다. 관리자에게 문의하십시오.",
                             url=request.url_for('login').__str__())

    # 가입된 소셜 서비스 아이디가 존재하는지 확인
    gnu_social_id = social_service.g5_convert_social_id(identifier, provider_name)
    if mb_id := social_service.get_member_by_social_id(gnu_social_id, provider_name):
        # 이미 가입된 회원이라면 로그인
        with SessionLocal() as db:
            member = db.query(Member.mb_id, Member.mb_datetime).filter(Member.mb_id == mb_id).first()

        if not member:
            raise AlertException(
                status_code=400, detail="유효하지 않은 요청입니다.",
                url=request.url_for('login').__str__())

        request.session["ss_mb_id"] = member.mb_id
        # XSS 공격에 대응하기 위하여 회원의 고유키를 생성해 놓는다.
        request.session["ss_mb_key"] = session_member_key(request, member)
        return RedirectResponse(url="/", status_code=302)

    if 'ss_social_link' in request.session and request.state.login_member.mb_id:
        # 소셜 가입 연결
        member = request.state.login_member
        profile.mb_id = member.mb_id
        db = SessionLocal()
        db.add(profile)
        db.commit()
        db.close()
        return RedirectResponse(url=request.url_for('index'), status_code=302)

    # 회원가입
    request.session['ss_social_provider'] = provider_name
    request.session['ss_social_email'] = social_email
    return RedirectResponse(url=request.url_for('get_social_register_form'), status_code=302)


@router.get('/social/register')
async def get_social_register_form(request: Request):
    """
    소셜 회원가입 폼
    """
    config = request.state.config
    if not config.cf_social_login_use:
        raise AlertException(status_code=400, detail="소셜로그인을 사용하지 않습니다.")

    provider_name = request.session.get("ss_social_provider", None)
    if (request.session.get('ss_social_access', None) is None) or (provider_name is None):
        raise AlertException(status_code=400, detail="먼저 소셜로그인을 하셔야됩니다.",
                             url=request.url_for('login').__str__())
    social_email = request.session.get('ss_social_email', None)
    is_exists_email = False if social_email is None else True

    form_context = {
        "social_member_id": "",  # g5 user_id
        "social_member_email": social_email,  # user_email
        "action_url": request.url_for('post_social_register'),
        "is_exists_email": is_exists_email,
    }
    return templates.TemplateResponse("social/social_register_member.html", {
        "request": request,
        "config": config,
        "form": form_context,
        "provider_name": provider_name,
    })


@router.post('/social/register')
async def post_social_register(
        request: Request,
        member_form: MemberForm = Depends(),
        db: Session = Depends(get_db),
):
    """
    신규 소셜 회원등록
    """
    config = request.state.config
    if not config.cf_social_login_use:
        raise AlertException(status_code=400, detail="소셜로그인을 사용하지 않습니다.",
                             url=request.url_for('login').__str__())

    provider_name = request.session.get("ss_social_provider", None)
    if (request.session.get('ss_social_access', None) is None) or (provider_name is None):
        raise AlertException(status_code=400, detail="유효하지 않은 요청입니다. 관리자에게 문의하십시오.",
                             url=request.url_for('login').__str__())

    auth_token = request.session.get('ss_social_access', None)
    provider_module_name = getattr(providers, f"{provider_name}")
    provider_class: SocialProvider = getattr(provider_module_name, f"{provider_name.capitalize()}")
    response = await get_social_profile(auth_token, provider_name, request)
    social_email, profile = provider_class.convert_gnu_profile_data(response)

    # token valid

    identifier = str(profile.identifier)
    if not identifier:
        logging.critical(
            f'social login identifier is empty, gnu profile convert parsing error. '
            f'social_provider: {provider_name}, profile: {profile}')
        raise AlertException(status_code=400, detail="유효하지 않은 요청입니다. 관리자에게 문의하십시오.",
                             url=request.url_for('login').__str__())

    social_service = SocialAuthService()
    gnu_social_id = social_service.g5_convert_social_id(identifier, provider_name)
    exists_social_member = db.query(Member.mb_id, Member.mb_email).filter(Member.mb_id == gnu_social_id).first()

    # 유효성 검증
    if exists_social_member:
        raise AlertException(status_code=400, detail="이미 소셜로그인으로 가입된 회원아이디 입니다.", url=request.url_for('login').__str__())

    result = validate_userid(gnu_social_id, config.cf_prohibit_id)
    if result["msg"]:
        raise AlertException(status_code=400, detail=result["msg"])

    if not valid_email(member_form.mb_email):
        raise AlertException(status_code=400, detail="이메일 양식이 올바르지 않습니다.")

    exists_email = db.query(Member.mb_email).filter(Member.mb_email == member_form.mb_email).first()
    if exists_email:
        raise AlertException(status_code=400, detail="이미 존재하는 이메일 입니다.")

    result = validate_nickname(member_form.mb_nick, config.cf_prohibit_id)
    if result["msg"]:
        raise AlertException(status_code=400, detail=result["msg"])

    # nick
    mb_nick = member_form.mb_nick
    if not mb_nick:
        mb_nick = gnu_social_id.split('_')[1]

    request_time = datetime.now()

    # 유효성 검증 통과
    member_social_profiles = MemberSocialProfiles()
    member_social_profiles.mb_id = gnu_social_id
    member_social_profiles.provider = provider_name
    member_social_profiles.identifier = gnu_social_id
    member_social_profiles.nickname = mb_nick
    member_social_profiles.profile_url = profile.profile_url
    member_social_profiles.photourl = profile.photourl
    member_social_profiles.object_sha = ""  # 사용하지 않는 데이터.
    member_social_profiles.mp_register_day = request_time

    member = Member()
    member.mb_id = gnu_social_id
    member.mb_password = hash_password(hash_password(str(request_time.microsecond)))
    member.mb_name = mb_nick
    member.mb_nick = mb_nick
    member.mb_email = member_form.mb_email
    member.mb_datetime = request_time
    member.mb_today_login = request_time
    member.mb_level = config.cf_register_level
    db.add(member)
    db.add(member_social_profiles)
    db.commit()

    # 가입시 발생 이벤트
    datetime_str = request_time.strftime("%Y-%m-%d %H:%M:%S")
    insert_point(
        request,
        mb_id=member.mb_id,
        point=config.cf_register_point,
        content=datetime_str + " 첫로그인",
        rel_table="@login",
        rel_id=member.mb_id,
        rel_action="회원가입"
    )

    # todo // 최고관리자에게 메일 발송

    return RedirectResponse(url="/", status_code=302)


class SocialAuthService:

    @classmethod
    def get_member_by_social_id(cls, identifier, provider) -> Optional[str]:
        """
        소셜 서비스 아이디로 그누보드5 회원 아이디를 가져옴
        Args:
            identifier (str) : 소셜서비스 사용자 식별 id
            provider (str) : 소셜 제공자
        Returns:
            g5 user_id
        """
        with SessionLocal() as db:
            result = db.query(MemberSocialProfiles.mb_id).filter(
                MemberSocialProfiles.provider == provider,
                MemberSocialProfiles.identifier == identifier
            ).first()

        if result:
            return result.mb_id

        return None

    @classmethod
    def check_exists_social_id(cls, identifier, provider) -> bool:
        """
        소셜 서비스 아이디가 존재하는지 확인
        Args:
            identifier (str) : 소셜서비스 사용자 식별 id
            provider (str) : 소셜 제공자
        Returns:
            True or False
        """
        with SessionLocal() as db:
            result = db.query(MemberSocialProfiles).filter(
                MemberSocialProfiles.provider == provider,
                MemberSocialProfiles.identifier == identifier
            ).first()

        if result:
            return True

        return False

    @classmethod
    def g5_convert_social_id(cls, identifier, provider: str):
        """
        그누보드5 소셜 id 생성 함수 get_social_convert_id
        provider + uid로 부터 고유 해시값생성
        Args:
            identifier (str) : 소셜서비스 사용자 식별 id
            provider (str) : 소셜 제공자
        Returns:
            provider_hax(adler32(md5(uid)))
        """
        md5_hash = hashlib.md5(identifier.encode()).hexdigest()
        # Adler-32 hash on the hexadecimal MD5 hash
        adler32_hash = zlib.adler32(md5_hash.encode())

        return f"{provider}_{hex(adler32_hash)[2:]}"