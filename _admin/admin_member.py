from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from database import get_db
import models 
import datetime
from common import *

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)
# 파이썬 함수 및 변수를 jinja2 에서 사용할 수 있도록 등록
templates.env.globals['getattr'] = getattr
templates.env.globals['today'] = SERVER_TIME.strftime("%Y%m%d")
templates.env.globals['get_member_level_select'] = get_member_level_select

@router.get("/member_list")
def member_list(request: Request, db: Session = Depends(get_db)):
    members = db.query(models.Member).all()
    return templates.TemplateResponse("admin/member_list.html", {"request": request, "members": members})

# 등록폼
@router.get("/member_form")
def member_form_add(request: Request, db: Session = Depends(get_db)):
    request.session["ss_member_form_mb_id"] = ""
    token = hash_password("")
    return templates.TemplateResponse("admin/member_form.html", {"request": request, "token": token })

# 수정폼
@router.get("/member_form/{mb_id}")
def member_form_edit(mb_id: str, request: Request, db: Session = Depends(get_db)):
    sst = request.state.sst
    sod = request.state.sod
    sfl = request.state.sfl
    stx = request.state.stx
    page = request.state.page
    
    # print(request.state.sfl)
    
    member = db.query(models.Member).filter(models.Member.mb_id == mb_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="{mb_id} is not found.")
    request.session["ss_member_form_mb_id"] = mb_id
    token = hash_password(mb_id)
    return templates.TemplateResponse("admin/member_form.html", {"request": request, "member": member, "token": token })

# DB등록 및 수정
@router.post("/member_form_update")
def member_form_update(request: Request, db: Session = Depends(get_db),
                       mb_id: str = Form(...),
                       token: str = Form(...),
                       mb_password: str = Form(None),
                       mb_name: str = Form(None),
                       mb_nick: str = Form(None),
                       mb_level: int = Form(None),
                       mb_email: str = Form(None),
                       mb_homepage: str = Form(None),
                       mb_hp: str = Form(None),
                       mb_tel: str = Form(None),
                       mb_certify_case: str = Form(None),
                       mb_certify: int = Form(None),
                       mb_adult: int = Form(None),
                       mb_zip: str = Form(None),
                       mb_addr1: str = Form(None),
                       mb_addr2: str = Form(None),
                       mb_addr3: str = Form(None),
                       mb_mailling: int = Form(None),
                       mb_sms: int = Form(None),
                       mb_open: int = Form(None),
                       mb_signature: str = Form(None),
                       mb_profile: str = Form(None),
                       mb_memo: str = Form(None),
                       mb_intercept_date: str = Form(None),
                       mb_leave_date: str = Form(None),
                       mb_1: str = Form(None),
                       mb_2: str = Form(None),
                       mb_3: str = Form(None),
                       mb_4: str = Form(None),
                       mb_5: str = Form(None),
                       mb_6: str = Form(None),
                       mb_7: str = Form(None),
                       mb_8: str = Form(None),
                       mb_9: str = Form(None),
                       mb_10: str = Form(None),
                       ):
    # 세션에 값이 있다면 수정, 없다면 등록
    ss_member_form_mb_id = request.session.get("ss_member_form_mb_id", "")
    # if not ss_member_form_mb_id: # 등록
    if not verify_password(mb_id, token): # 등록 (수정시 토큰이 변조 되었다면 등록으로 처리)
        chk_member = db.query(models.Member).filter(models.Member.mb_id == mb_id).first()
        if chk_member:
            # 수정시 토큰이 변조 되었다면 이 에러를 만나게 된다.
            raise HTTPException(status_code=404, detail=f"{mb_id} : 회원아이디가 이미 존재합니다.")
        
        chk_member = db.query(models.Member).filter(models.Member.mb_nick == mb_nick).first()
        if chk_member:
            raise HTTPException(status_code=404, detail=f"{mb_nick} : 닉네임이 이미 존재합니다. ({chk_member.mb_id})")
        
        chk_member = db.query(models.Member).filter(models.Member.mb_email == mb_email).first()
        if chk_member:
            raise HTTPException(status_code=404, detail=f"{mb_email} : 이메일이 이미 존재합니다. ({chk_member.mb_id})")
        
        if mb_certify_case and mb_certify:
            tmp_certify = mb_certify_case
            tmp_adult = mb_adult
        else:
            tmp_certify = ''
            tmp_adult = 0 
            
        if mb_password:
            hashed_password = hash_password(mb_password)               
        else:
            hashed_password = hash_password(TIME_YMDHIS) # 비밀번호가 없다면 현재시간으로 해시값을 만듬 (알수없게 만드는게 목적)
            
        member = models.Member(
            mb_id=mb_id, 
            mb_password=hashed_password, 
            mb_name=mb_name, 
            mb_nick=mb_nick,
            mb_level=mb_level,            
            mb_nick_date=TIME_YMDHIS,
            mb_email=mb_email,
            mb_homepage=mb_homepage,
            mb_hp=mb_hp,
            mb_tel=mb_tel,
            mb_certify=tmp_certify,
            mb_adult=tmp_adult,
            mb_zip1=mb_zip[:3] if mb_zip else '',
            mb_zip2=mb_zip[3:] if mb_zip else '',
            mb_addr1=mb_addr1,
            mb_addr2=mb_addr2,
            mb_addr3=mb_addr3,
            mb_mailling=mb_mailling,
            mb_sms=mb_sms,
            mb_open=mb_open,
            mb_signature=mb_signature,
            mb_profile=mb_profile,
            mb_memo=mb_memo,
            mb_intercept_date=mb_intercept_date,
            mb_leave_date=mb_leave_date,
            mb_1=mb_1,
            mb_2=mb_2,
            mb_3=mb_3,
            mb_4=mb_4,
            mb_5=mb_5,
            mb_6=mb_6,
            mb_7=mb_7,
            mb_8=mb_8,
            mb_9=mb_9,
            mb_10=mb_10,
            mb_today_login=TIME_YMDHIS,
            mb_datetime=TIME_YMDHIS,
        )
        db.add(member)
        db.commit()
        
    else: # 수정
        if not verify_password(mb_id, token):
            raise HTTPException(status_code=403, detail="Invalid token.")
        
        chk_member = db.query(models.Member).filter(and_(models.Member.mb_id != mb_id, models.Member.mb_nick == mb_nick)).first()
        if chk_member is not None:
            raise HTTPException(status_code=404, detail=f"{mb_nick} : 닉네임이 이미 존재합니다. ({chk_member.mb_id})")
        
        chk_member = db.query(models.Member).filter(and_(models.Member.mb_id != mb_id, models.Member.mb_email == mb_email)).first()
        if chk_member:
            raise HTTPException(status_code=404, detail=f"{mb_email} : 이메일이 이미 존재합니다. ({chk_member.mb_id})")
        
        config = request.state.context['config']
        
        member = db.query(models.Member).filter(models.Member.mb_id == ss_member_form_mb_id).first()
        if not member:
            raise HTTPException(status_code=404, detail=f"{mb_id} : 회원아이디가 존재하지 않습니다.")
        
        if mb_password:
            member.mb_password = hash_password(mb_password)
        member.mb_name = mb_name if mb_name else ''
        member.mb_nick = mb_nick if mb_nick else ''
        member.mb_nick_date = TIME_YMD if mb_nick else ''
        member.mb_email = mb_email if mb_email else ''
        member.mb_homepage = mb_homepage if mb_homepage else ''
        member.mb_level = mb_level if mb_level else config.cf_register_level
        member.mb_hp = mb_hp if mb_hp else ''
        member.mb_tel = mb_tel if mb_tel else ''
        member.mb_certify = mb_certify_case if (mb_certify_case and mb_certify == 1) else ''
        member.mb_adult = mb_adult if mb_adult else 0
        member.mb_zip1 = mb_zip[:3] if mb_zip else ''
        member.mb_zip2 = mb_zip[3:] if mb_zip else ''
        member.mb_addr1 = mb_addr1 if mb_addr1 else ''
        member.mb_addr2 = mb_addr2 if mb_addr2 else ''
        member.mb_addr3 = mb_addr3 if mb_addr3 else ''
        member.mb_mailling = mb_mailling if mb_mailling else 0
        member.mb_sms = mb_sms if mb_sms else 0
        member.mb_open = mb_open if mb_open else 0
        member.mb_signature = mb_signature if mb_signature else ''
        member.mb_profile = mb_profile if mb_profile else ''
        member.mb_memo = mb_memo if mb_memo else ''
        member.mb_intercept_date = mb_intercept_date if mb_intercept_date else ''
        member.mb_leave_date = mb_leave_date if mb_leave_date else ''
        member.mb_1 = mb_1 if mb_1 else ''
        member.mb_2 = mb_2 if mb_2 else ''
        member.mb_3 = mb_3 if mb_3 else ''
        member.mb_4 = mb_4 if mb_4 else ''
        member.mb_5 = mb_5 if mb_5 else ''
        member.mb_6 = mb_6 if mb_6 else ''
        member.mb_7 = mb_7 if mb_7 else ''
        member.mb_8 = mb_8 if mb_8 else ''
        member.mb_9 = mb_9 if mb_9 else ''
        member.mb_10 = mb_10 if mb_10 else ''
        db.commit()
        mb_id = ss_member_form_mb_id
    return RedirectResponse(url=f"/admin/member_form/{mb_id}", status_code=302)