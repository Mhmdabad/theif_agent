# Chapter 8 — Agent Architecture and Reliability

> **Source:** [Distributed Cops-and-Robbers over a Peer-to-Peer Network, v3.0.0](https://github.com/rmisegal/Game-P2P-Cop-Chase/blob/master/docs/police_thief_p2p.pdf)
> **Physical PDF pages:** 77–84
> **Source SHA-256:** `7c9e1d7527582c3aef9afd71709981cea50ea60b8fabefe85efccab0a5fdd02e`
>
> Curated Markdown transcription for repository-local study. The source PDF remains authoritative; Appendix F is the sole authority for binding quantitative parameters. Hebrew/English bidirectional text, equations, and complex visual layouts may render differently from the PDF.
>
> Copyright © 2026 Dr. Yoram Segal / Gal Technologies Artificial Intelligence Ltd. All rights reserved. Authorized educational use only under the source terms; no commercial use or redistribution.

[← Chapter 7 — GUI and Replay Simulator](07-gui-and-replay-simulator.md) · [Contents](README.md) · [Chapter 9 — League, Computational Fairness, and Reporting →](09-league-fairness-and-reporting.md)

---

<!-- source-pdf-page: 77 -->

## פרק 8 — עיצוב ארכיטקטורת הסוכן ומנגנוני אמינות עמוקים
### מטרות הפרק 8.1
בסיום פרק זה תדעו: מדוע סוכן משחק אוטונומי איננו סקריפט לינארי אלא Separation ) _הפרדת האחריות_ מערכת מבוזרת הדורשת פיתוח קפדני לפי עקרון מרכזת את כל תת-המערכות מאחורי Orchestrator(;כיצד תבנית ה-of Concerns שער כניסה יחיד ומכפיפה את מהלך המשחק למכונת מצבים חוקית; ומהם —המגנים על הסוכן מפני WatchdogוDeadline Tracker דפוסי היציבות — קיפאון ומפני נתקים ברשת עמית-לעמית.

### Separation of Concerns הפרדת אחריות כעיקרון-על 8.2
מדוע מערכת שמנצחת בסימולציה נכשלת לעיתים במשחק אמיתי מול יריב מרוחק? התשובה נעוצה לרוב לא באלגוריתם ההחלטה אלא בפיתוח המערכת סוכן המשתתף במשחק רב-משתתפים מבוסס בינה מלאכותית, כפי סביבו. שממליצים הפרוטוקולים לתחום זה, אינו יכול לערבב בקוד אחד את ניהול התקשורת, את קבלת ההחלטות ואת רישום היומנים. עירוב כזה מוליד מערכת

שברירית שבה תקלה בתת-מערכת אחת מפילה את כולן. הפתרון הפיתוחי הוא חלוקה למודולים בעלי אחריות בודדת וברורה, המתואמים בידי רכיב מרכזי אחד. הפרק שלפניכם עוסק בשלד הארכיטקטוני (שמשמש שער יחיד לכל תת-המערכות,Orchestrator ) _מתזמר_ הזה: כיצד בונים וכיצד עוטפים אותו בשכבת אמינות שמניחה מראש שהעולם — הרשת, המודל, .[30] והיריב — ייכשל בדיוק ברגע הקריטי

---

<!-- source-pdf-page: 78 -->

### Orchestrator and ומכונת המצבים Orchestratorתבנית ה- 8.3 State Machine
—שער כניסה יחיד — Gateway בלב הארכיטקטורה עומד רכיב מרכזי המשמש (,מפעיל2 )פרק MCPלכל תת-המערכות. המתזמר הוא שמאתחל את חיבורי ה- (,ומתקשר עם מנהלי היומנים ומנגנוני ההתחייבות6 את מודול ההחלטה )פרק (.במקום שכל מודול יכיר את רעהו ישירות )מבנה5 הקריפטוגרפיים )פרק שמוליד תלות הדדית סבוכה(, כל התקשורת עוברת דרך נקודה אחת. תבנית ועל דפוסי שער-כניסה [31] זו נשענת על עקרונות עיצוב מוכרים בפיתוח תוכנה .[5] מעולם המיקרו-שירותים

### —מתזמר Orchestrator
(לכלSingle Gatewayרכיב תוכנה מרכזי המשמש נקודת כניסה יחידה ) תת-המערכות של הסוכן. הוא אחראי לאתחול החיבורים, להפעלת מודול ההחלטה, לתיאום בין הרכיבים ולתקשורת עם מנהלי היומנים — אך אינו מכיל בעצמו לוגיקת החלטה או תקשורת ברמה נמוכה. תפקידו לתאם, לא לבצע.

(קפדנית, המבטיחהState Machineהמשחק כולו נשלט בידי מכונת מצבים ) WAITשרק מעברים חוקיים בין שלבי המשחק יתאפשרו. שלב ההמתנה ליריב ) COMPUT(יכול לעבור אך ורק לשלב חישוב המהלך )ING_FOR_OPPONENT (,וכן הלאה.COMMITTING(,וזה בתורו אל שלב ההתחייבות )ING_MOVE (שבהם שניDeadlockמעבר בלתי-חוקי נדחה מיד, ובכך נמנעים מצבי קיפאון ) הצדדים ממתינים זה לזה עד אינסוף.

### —קיפאון Deadlock
מצב שבו שתי ישויות או יותר ממתינות זו למשאב או להודעה שבידי רעותה, כך שאף אחת אינה יכולה להתקדם. במערכת עמית-לעמית ללא שופט מרכזי, קיפאון עלול לתקוע משחק שלם ללא כל הודעת שגיאה. מכונת מצבים החוסמת מעברים בלתי-חוקיים היא קו ההגנה הראשון מפני קיפאון.

---

<!-- source-pdf-page: 79 -->

<details>
<summary>Figure text extracted from the source PDF</summary>

```text
WAITING_FOR_
COMPUTING_MOVE COMMITTING
OPPONENT
TECHNICAL_LOSS VERIFYING AWAITING_REVEAL
```

</details>

המערכת עוברת :מכונת המצבים החוקית של תור משחק בודד:11 איור במחזוריות בין המתנה ליריב, חישוב מהלך, התחייבות, המתנה לחשיפה ואימות; חץ שגיאה מקווקו מוביל מכל שלב תקשורתי אל הפסד טכני.

WAIT חמישה מצבים תקינים המסודרים במעגל — **מה רואים באיור:** AWAIT ,COMMITTING ,COMPUTING_MOVE ,ING_FOR_OPPONENT —כאשר האימות מחזיר את המערכת להמתנה VERIFYINGוING_REVEAL ,שאליו מוביליםTECHNICAL_LOSS בנוסף מופיע מצב שגיאה, לתור הבא. החצים המלאים הם המעברים החוקיים **כיצד לפרש:** חצים מקווקווים. היחידים; כל ניסיון לקפוץ ממצב אחד למצב שאינו יעד חוקי שלו נדחה. החצים המקווקווים מייצגים יציאת חירום — מעבר לשלב תקשורתי שנכשל. ,AWAITING_REVEAL אם היריב מתנתק בזמן **ניתוח ״מה יקרה אם״:** המערכת אינה נתקעת בהמתנה נצחית אלא עוברת באורח מבוקר אל ומודיעה על תוצאה — בדיוק ההתנהגות שמכונת מצבים TECHNICAL_LOSS

חוקית מבטיחה. מימוש מכונת המצבים נשען על טבלת מעברים המפרטת, לכל מצב, אילו הקוד הבא משרטט מחלקה מינימלית הדוחה כל מעבר מצבי-יעד חוקיים. שאינו רשום בטבלה:

---

<!-- source-pdf-page: 80 -->

### דוגמה: מכונת מצבים עם טבלת מעברים

```python
class GamePhaseMachine:
    # Transition table: each state maps to its set of legal successors.
    TRANSITIONS = {
        "WAITING_FOR_OPPONENT": {"COMPUTING_MOVE"},
        "COMPUTING_MOVE": {"COMMITTING", "TECHNICAL_LOSS"},
        "COMMITTING": {"AWAITING_REVEAL"},
        "AWAITING_REVEAL": {"VERIFYING", "TECHNICAL_LOSS"},
        "VERIFYING": {"WAITING_FOR_OPPONENT"},
        "TECHNICAL_LOSS": set(),  # terminal state
    }

    def __init__(self):
        self.state = "WAITING_FOR_OPPONENT"

    def transition(self, target):
        # Reject any transition not listed in the table.
        if target not in self.TRANSITIONS[self.state]:
            raise ValueError(f"Illegal transition: {self.state} -> {target}")
        self.state = target
        return self.state
```

המחלקה שומרת את המצב הנוכחי, וכל בקשת מעבר נבדקת מול קבוצת היעדים החוקיים. מעבר בלתי-חוקי מעורר חריגה מיידית במקום להשאיר את המערכת במצב לא-מוגדר — כך הופכים באג לוגי לשגיאה גלויה שנתפסת בזמן פיתוח, ולא לקיפאון שקט בזמן משחק.

---

<!-- source-pdf-page: 81 -->

### Reliability WatchdogוDeadline Tracker דפוסי אמינות: 8.4
### Patterns
(חשופות מטבען לנתקים ולעיכובים קריטיים במודלP2Pמערכות עמית-לעמית ) השפה. סוכן חסון אינו יכול להניח שכל בקשה תיענה; עליו לממש דפוסי מעקב .שני הדפוסים[30] אקטיביים המבחינים בין ״עדיין ממתין״ ל״נכשל ויש לפעול״ (.Watchdog(וכלב-שמירה )Deadline Trackerהמרכזיים כאן הם עוקב-מועד ) המווסת את הדואר היוצא — נדון Gatekeeperדפוס אמינות משלים — ה- .9 בהקשר הליגה בפרק

**—עוקב מועדים Deadline Tracker 8.4.1** (Timestampנושאת חותמת זמן ) FastMCPכל בקשה הנשלחת מעל שרת ה- (.אם לא הגיעה תשובה בתוך הזמן המוקצב,Expiry Deadlineומועד תפוגה ) דפוס (או משדרת הודעת הפסד-טכני.Retryהמערכת מבצעת ניסיון חוזר ) מספרות היציבות: לעולם אל Timeoutזה הוא מימוש קונקרטי של תבנית ה- תמתין ללא גבול למשאב חיצוני שאינו בשליטתך.

### החמצת מועד היא כשל, לא סבלנות
להיחשב ככשל — ולא כהזמנה _חייבת_ בקשה שחלף מועד התפוגה שלה השארת בקשה ״תלויה״ ללא מועד תפוגה היא המתכון להמתין עוד. התהליך הראשי נתקע בהמתנה, כלב-השמירה מזהה הישיר לקיפאון: לשאת מועד MCP שאין פעימת-לב, והמשחק קורס. על כל בקשה מעל מבוקר או להכריז על Retry תפוגה, ובחלוף המועד על המערכת לבצע הפסד טכני ולסגור את התור בצורה נקייה.

**—כלב שמירה Watchdog 8.4.2** שומר על Watchdogשומר על בקשה בודדת, ה- Deadline Trackerבעוד ה- המערכת כולה. זהו תהליך רקע עצמאי המנטר את לולאת המשחק הראשית. אם הוא מזהה שהמערכת קפאה למשך דקות ארוכות ללא פליטת פעימת—עקב קריסת מודל או כשל תקשורת — הוא יכול לבצע (Heartbeatלב ) (לצורךState Persistence(ולשמר את המצב )Controlled Shutdownכיבוי מבוקר ) התאוששות מאוחרת יותר.

---

<!-- source-pdf-page: 82 -->

<details>
<summary>Figure text extracted from the source PDF</summary>

```text
Deadline Tracker
MCP Connector
Orchestrator
Decision Module
(Gateway)
Log Manager
Watchdog
:המתזמר משמש שער יחיד המתפצל אל חמש תת-מערכות: מחבר12 איור
כל ,מודול ההחלטה, מנהל היומנים, עוקב-המועדים וכלב-השמירה.MCPה-
תקשורת בין-מודולרית עוברת דרכו.
```

</details>

—שממנו יוצאים חצים Orchestrator רכיב מרכזי מודגש — ה- **מה רואים באיור:** ,Log Manager ,Decision Module ,MCP Connector אל חמישה מודולים נפרדים: כל חץ מייצג ערוץ שליטה יחיד; **כיצד לפרש:** .WatchdogוDeadline Tracker אין חצים בין המודולים ההיקפיים עצמם, ובכך מומחש עקרון השער היחיד — **ניתוח ״מה יקרה** אף מודול אינו מכיר את רעהו ישירות אלא רק את המתזמר. אם נרצה להחליף את מנוע ההחלטה במודל אחר, די בכך שנחליף מודול **אם״:** בודד ונשמר על אותו ממשק מול המתזמר; שאר המערכת אינה מושפעת —

זהו כוחה של הפרדת האחריות.

:בדיקת פעימת-לב תקופתיתWatchdogהקוד הבא משרטט את לב ה- המחליטה אם המערכת הראשית עדיין חיה:

---

<!-- source-pdf-page: 83 -->

### דוגמה: בדיקת פעימת־לב של ה־Watchdog

```python
import time

def watchdog_check(last_heartbeat, timeout_sec=180):
    # last_heartbeat: epoch time of the main loop's last signal.
    elapsed = time.time() - last_heartbeat
    if elapsed > timeout_sec:
        # Main loop appears frozen: persist state and shut down cleanly.
        persist_state()        # save game state for later recovery
        controlled_shutdown()  # release MCP connections, close logs
        return "SHUTDOWN"
    return "ALIVE"
```

התהליך משווה את הזמן שחלף מאז פעימת-הלב האחרונה אל סף קבוע. כל עוד הלולאה הראשית פולטת פעימה בקצב סדיר, ה־Watchdog מחזיר `ALIVE` ואינו מתערב. אך אם חלפו יותר מן הסף הקצוב — סימן שהמודל קרס או שהתקשורת נתקעה — הוא משמר את המצב ומבצע כיבוי מבוקר, כך שניתן יהיה להתאושש מאוחר יותר במקום לאבד את המשחק כולו.

---

<!-- source-pdf-page: 84 -->

### חיבור לקורס
רעיון המתזמר כשער-כניסה יחיד לתת-סוכנים איננו חדש לכם. בהרצאה ,שעסקה בסוכנים ותת-סוכנים, _I אורקסטרציה של סוכניA_ של הקורס L05 (מאציל עבודה לקבוצת תת-סוכניםOrchestratorראיתם כיצד סוכן-על ) (,Commands(ופקודות )Skillsהוא מפעיל מיומנויות ) דרך שער יחיד: ומרכז את כל זרימת המידע ביניהם במקום שכל רכיב יפנה ישירות לרעהו. של סוכן המשחק הוא בדיוק אותו דפוס, מוקשח לתנאי Orchestratorה,מודול ההחלטה, מנהלMCPתת-המערכות )מחבר ה- משחק תחרותי: היומנים, עוקב-המועדים וכלב-השמירה( הן ה״תת-סוכנים״, וההאצלה דרך שער יחיד — אותה הפרדת אחריות — היא שמאפשרת להחליף, לבדוד ולתקן כל רכיב בנפרד. כיוון ששני הצדדים במשחק בנויים באופן סימטרי, כל אחד מהם מריץ מתזמר ומכונת-מצבים משלו לפי אותו דפוס בדיוק.

**סיכום הפרק 8.5**

תיאום ראינו שסוכן משחק אמין נבנה על שני עמודי-תווך של פיתוח: ואמינות. המתזמר מרכז את כל תת-המערכות מאחורי שער יחיד ומכפיף את מהלך המשחק למכונת מצבים החוסמת מעברים בלתי-חוקיים ומונעת קיפאון. מניחים מראש שהרשת והמודל ייכשלו, WatchdogוהDeadline Trackerדפוסי ה- עם ומספקים ניסיון-חוזר, כיבוי מבוקר ושימור מצב במקום קריסה שקטה. שלד אמין זה בידינו, נפנה בפרק הבא אל השכבה שמעליו — הלוגיקה האסטרטגית שממלאת את מודול ההחלטה בתוכן.

---

[← Chapter 7 — GUI and Replay Simulator](07-gui-and-replay-simulator.md) · [Contents](README.md) · [Chapter 9 — League, Computational Fairness, and Reporting →](09-league-fairness-and-reporting.md)
