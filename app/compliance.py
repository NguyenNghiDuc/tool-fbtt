import re
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

CLAIMS = [r'cam kết.{0,20}(khỏi|chữa|giảm|100%)', r'chữa.{0,15}(khỏi|bệnh)',
          r'100%\s*(an toàn|hiệu quả)', r'guaranteed\s+(cure|results)', r'không có tác dụng phụ']

class ReviewConfirmation(BaseModel):
    acknowledged: bool = False

class ReviewText(BaseModel):
    text: str = Field(max_length=5000)

def warnings(text):
    found = []
    if any(re.search(pattern, text, re.I) for pattern in CLAIMS):
        found.append('Caption có cam kết sức khỏe/hiệu quả; kiểm tra bằng chứng và chính sách nền tảng.')
    if '#quảngcáo' not in text.lower():
        found.append('Thiếu dòng công khai quảng cáo/affiliate.')
    return found

def install(app, db, current_user):
    def review_job(jid):
        rows = db.query('SELECT * FROM jobs WHERE id=?', (jid,))
        if not rows:
            raise HTTPException(404, 'Job not found')
        job = rows[0]
        result = warnings(job['caption'])
        if db.query('SELECT 1 FROM assignments WHERE media_id=? AND profile_id!=?', (job['media_id'], job['profile_id'])):
            result.append('Video được gán cho nhiều tài khoản; có nguy cơ nội dung trùng lặp.')
        return {'warnings': result, 'requires_acknowledgment': bool(result),
                'notice': 'Chỉ đăng nội dung có quyền sử dụng và dùng tài khoản đã được chủ sở hữu ủy quyền.'}
    @app.get('/api/jobs/{jid}/review')
    def review(jid: int, user=Depends(current_user)):
        return review_job(jid)
    @app.post('/api/compliance/review')
    def review_text(body: ReviewText, user=Depends(current_user)):
        return {'warnings': warnings(body.text), 'notice':'Đây là cảnh báo theo từ khóa, không thay thế kiểm duyệt nội dung.'}
    app.state.review_job = review_job
