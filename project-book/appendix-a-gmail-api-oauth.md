# Appendix A — Gmail API and OAuth 2.0

> **Source:** [Distributed Cops-and-Robbers over a Peer-to-Peer Network, v3.0.0](https://github.com/rmisegal/Game-P2P-Cop-Chase/blob/master/docs/police_thief_p2p.pdf)
> **Physical PDF pages:** 120–125
> **Source SHA-256:** `7c9e1d7527582c3aef9afd71709981cea50ea60b8fabefe85efccab0a5fdd02e`
>
> Curated Markdown transcription for repository-local study. The source PDF remains authoritative; Appendix F is the sole authority for binding quantitative parameters. Hebrew/English bidirectional text, equations, and complex visual layouts may render differently from the PDF.
>
> Copyright © 2026 Dr. Yoram Segal / Gal Technologies Artificial Intelligence Ltd. All rights reserved. Authorized educational use only under the source terms; no commercial use or redistribution.

[← References](12-references.md) · [Contents](README.md) · [Appendix B — Unified Configuration →](appendix-b-unified-configuration.md)

---

<!-- source-pdf-page: 120 -->

## נספח א — מדריך הגדרת Gmail API ו־OAuth 2.0
תשתית הדיווח האוטומטי של הפרויקט — שבה סוכן שולח לעצמו, למנחה או לצוות דוחות מצב בסיום כל ריצה — נשענת על יכולת שליחת דואר אלקטרוני .אלא שגישה מודרנית ומאובטחת אינה משתמשתGmail API תוכניתית דרך (Token ) _אסימון_ במקום זאת היא נשענת על בסיסמת המשתמש הרגילה: .תקן זה מפריד בין זהות המשתמש[34] OAuth 2.0 מאובטח המונפק בתקן לבין ההרשאה שהוא מעניק לאפליקציה, ובכך מאפשר לסוכן לפעול בשמכם מבלי שסודכם האישי ייחשף אי-פעם בקוד. נספח זה מוליך אתכם, צעד אחר צעד, מהקמת הפרויקט בענן ועד לזרימת ההרשאה הראשונה שמעניקה לסוכן .[32] אוטונומיה מלאה

### The Five Setup Steps חמשת שלבי ההגדרה 1
התהליך המלא מורכב מחמישה שלבים סדורים. בצעו אותם לפי הסדר; דילוג על שלב )במיוחד על הגדרת מסך ההסכמה( יגרום לזרימת ההרשאה להיכשל

בשלב מאוחר ומבלבל יותר.

### Cloud Console שלב א׳: פתיחת פרויקט והפעלת השירות 1.1
וצרו פרויקט חדש )או בחרו קיים(. בתוך Google Cloud Console היכנסו אל .Gmail APIוהפעילו במפורש את שירות ה- APIהפרויקט, גשו אל ספריית ה- שהפרויקט שלכם רשאי לקרוא Google הפעלה זו היא שמסמנת לתשתית של לנקודות הקצה של הדואר.

---

<!-- source-pdf-page: 121 -->

### OAuth Consent Screen שלב ב׳: הגדרת מסך ההסכמה 1.2
Google —המסך שבו (OAuth Consent Screenהגדירו את מסך ההסכמה ) External מיידעת את המשתמש אילו הרשאות האפליקציה מבקשת. בחרו במצב (,Google Workspace )בתוך ארגון בעל Internal )למשתמשים מחוץ לארגון( או Testוהוסיפו את כתובות הדואר של הסטודנטים לקבוצת משתמשי-הבדיקה ) ,רק משתמשים ברשימהTesting (המורשים. בזמן שהאפליקציה במצבUsers זו יורשו להשלים את זרימת ההרשאה.

### Scope Restriction שלב ג׳: צמצום ההרשאות למינימום ההכרחי 1.3
בלבד: הנדרש ההחלטי (למינימוםScope) ההרשאות היקף את הגדירו של דואר _שליחה_ .היקף זה מתירhttps://www.googleapis.com/auth/gmail.send (לפרויקט שאינו זקוק לה.read— ותו לא. אל תעניקו לעולם הרשאת קריאה ) מדובר בעיקרון אבטחת-מידע יסודי: ככל שהאסימון מסוגל לפחות, כך קטן הנזק אם ידלוף.

### Create Credentials שלב ד׳: יצירת אישורי הגישה 1.4
.הורידוDesktop Application מסוג OAuth Client ID צרו Credentials בעמוד **חובה** לתיקיית העבודה המקומית של הפרויקט. credentials.json את הקובץ ,כדיGitHub דחיפת קוד אל _לפני_ .gitignore להוסיף קובץ זה אל **מוחלטת** למנוע חשיפת סוד )במאגר ציבורי — לעולם כולו; ובמאגר פרטי המשותף עם המרצה — גם כלפיו(. שכחה בשלב זה היא אחת התקלות הנפוצות והמסוכנות

ביותר בפרויקטים מבוססי-ענן.

---

<!-- source-pdf-page: 122 -->

### First Authorization Flow שלב ה׳: זרימת ההרשאה הראשונה 1.5
יפתחו חלון דפדפן Google בהרצה הראשונה של הקוד, הספריות הרשמיות של בתום האישור ייווצר אוטומטית הקובץ ויבקשו מכם לאשר את ההרשאה. ארוך-חיים. Refresh Token קצר-חיים לצד Access Token ,המכילtoken.json ,הסוכן יוכל לשלוח דוחות באופן אוטונומי לחלוטין —Refresh Tokenהודות ל- במשך חודשים רבים וללא כל התערבות ידנית נוספת.

### קריטי: לעולם אל תדחפו סודות למאגר
token.json)המזהה הסודי של האפליקציה( ו- credentials.json שני הקבצים שקולה לפרסום GitHubדחיפתם ל- . _סודות_ )האסימונים החתומים( הם הוסיפו את שתי מפתח הכניסה לתיבת הדואר שלכם ברשות הרבים. commit ה- **לפני** .gitignore אל הקובץ token.jsonוcredentials.json השורות אחד בהיסטוריה, commitלאחר שסוד נדחף אף ל- זכרו: הראשון. (אתrotateמחיקתו מהקוד הנוכחי אינה מספיקה — עליכם להחליף ) האישורים בקונסולה.

**Token Anatomy Refresh מול Access אנטומיה של אסימון: 2** כדי להבין מדוע התשתית פועלת ללא סיסמאות, יש להבחין בין שני סוגי .[34] מגדיר OAuth 2.0 האסימונים שתקן

### Refresh Token מול Access Token
)לרוב פג בתוך כשעה( המצורף לכל _קצר-חיים_ —אסימון **Access Token** פקיעתו המהירה מצמצמת את חלון בפועל ומאשר אותה. API בקשת הסיכון אם ידלוף. של הדואר עצמו, API שאינו נשלח ל- _ארוך-חיים_ —אסימון **Refresh Token** חדש כאשר הקודם פג. הוא זה שמעניק Access Token אלא משמש להשגת תקף, אין Refresh Tokenלסוכן את האוטונומיה ארוכת-הטווח: כל עוד ה- צורך בהתערבות אנושית חוזרת.

ההבחנה בין שני סוגי האסימונים אינה תיאורטית בלבד — היא שמאפשרת ליישם הלכה למעשה עיקרון אבטחה מרכזי, שראוי להדגישו בפני עצמו.

---

<!-- source-pdf-page: 123 -->

**(Least Privilege) עקרון ההרשאה הפחותה**

בלבד, ולא היקף רחב יותר כגון gmail.send שימו לב שביקשנו את היקף _עקרון_ .זהו יישום ישיר שלmail.google.com או gmail.modify : העניקו לרכיב בדיוק את ההרשאות שהוא זקוק להן _ההרשאה הפחותה_ ; לפיכך אין כל סיבה _לשלוח_ למשימתו — ולא יותר. סוכן הדיווח צריך רק צמצום ההיקף הופך אסימון גנוב מנשק דואר. _למחוק_ או _לקרוא_ שיוכל רב-עוצמה לכלי מוגבל ובלתי-מזיק כמעט.

**SendOnly Flow Pythonמימוש: זרימת שליחה מינימלית ב- 3** token.jsonטעינת האסימון מ- הקוד שלהלן ממחיש את הזרימה המלאה: MIME ,הרכבת הודעתGmail)או יצירתו בפעם הראשונה(, בניית שירות ה- gmail.sendוקידודה, ולבסוף שליחתה. שימו לב שההיקף המבוקש מוגבל ל- בלבד, כמתחייב מעקרון ההרשאה הפחותה.

---

<!-- source-pdf-page: 124 -->

### שליחת דוח דרך Gmail API עם OAuth 2.0

```python
import base64
from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Least-privilege scope: send only, no read/modify access.
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

def get_service():
    # Reuse token.json if it exists; otherwise run the consent flow once.
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    return build("gmail", "v1", credentials=creds)

def send_report(service, to_addr, subject, body):
    message = MIMEText(body)  # build a plain-text MIME message
    message["to"] = to_addr
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()

if __name__ == "__main__":
    svc = get_service()
    send_report(svc, "grader@example.com", "Run report", "Episode finished.")
```

בפועל, בהרצה הראשונה מחליפים את הקריאה הטוענת אסימון קיים בזרימת ההרשאה `InstalledAppFlow.from_client_secrets_file(...)`, המייצרת את `token.json`; לאחר מכן כל ההרצות הבאות טוענות את האסימון הקיים ומרעננות אותו אוטומטית.

---

<!-- source-pdf-page: 125 -->

### Required Files סיכום הקבצים 4
שני קבצים בלבד נדרשים לתשתית, ושניהם סודיים ושניהם חייבים להיכלל .הטבלה שלהלן מסכמת את תפקידם ומקורם..gitignoreב-

,מקורם ורגישותםOAuth :הקבצים הנדרשים לתשתית5 טבלה

|**האם להוסיף**<br>**ל-**<br>**.gitignore**|**תוכן**|**מקור**|**קובץ**|
|---|---|---|---|
|כן — חובה|מזהה סודי של<br>האפליקציה|מקור —<br>הורדה<br>מהקונסולה|credentials.json|
|כן — חובה|אסימוני גישה<br>וריענון|נוצר —<br>בהרצה<br>הראשונה|token.json|

---

[← References](12-references.md) · [Contents](README.md) · [Appendix B — Unified Configuration →](appendix-b-unified-configuration.md)
