# Appendix C — GitHub Submission and Academic Report

> **Source:** [Distributed Cops-and-Robbers over a Peer-to-Peer Network, v3.0.0](https://github.com/rmisegal/Game-P2P-Cop-Chase/blob/master/docs/police_thief_p2p.pdf)
> **Physical PDF pages:** 133–137
> **Source SHA-256:** `7c9e1d7527582c3aef9afd71709981cea50ea60b8fabefe85efccab0a5fdd02e`
>
> Curated Markdown transcription for repository-local study. The source PDF remains authoritative; Appendix F is the sole authority for binding quantitative parameters. Hebrew/English bidirectional text, equations, and complex visual layouts may render differently from the PDF.
>
> Copyright © 2026 Dr. Yoram Segal / Gal Technologies Artificial Intelligence Ltd. All rights reserved. Authorized educational use only under the source terms; no commercial use or redistribution.

[← Appendix B — Unified Configuration](appendix-b-unified-configuration.md) · [Contents](README.md) · [Appendix D — Reference Code Repository →](appendix-d-reference-code.md)

---

<!-- source-pdf-page: 133 -->

## נספח ג — דרישות הגשה ב־GitHub ודוח אקדמי
חשוב להפנים נספח זה מגדיר את תנאי הסף הפורמליים להגשת הפרויקט. _ארטיפקט_ כבר בפתח: ההגשה איננה קובץ מקור בודד המצורף בדוא״ל, אלא )ציבורי, או פרטי ומשותף עמו(, מתועד, _הנגיש למרצה_ שלם — מאגר קוד _פיתוחי_ אופן ההגשה נמדד ומתויג — המספר את סיפורה של המערכת שבניתם. באותה קפדנות שבה נמדד הקוד עצמו, משום שבעולם האמיתי של מערכות (ושקיפות התהליךReproducibilityבינה מלאכותית מבוזרות, יכולת השחזור ) הן חלק בלתי נפרד מן התוצר.

### Repository, Branches :מבנה, ענפים ותיוגGitHubמאגר ה- 1 and Tagging
_ציבורי_ — או _נגיש למרצה_ מאורגן היטב, ה GitHub תשתית ההגשה היא מאגר . הדרישה **]** כתובת המרצה **[** במפורש עם כתובת המרצה _משותף_ (,אוpublic) לנגישות אינה גחמה טכנית אלא עמדה מקצועית: קוד מקצועי טוב נכתב כדי הפיתוח מתנהל באמצעות ענפים להיקרא, להיבחן, ולהישחזר בידי אחרים. —כל יכולת מהותית מתפתחת בענף ייעודי ומתמזגת אל הענף (Branches) הראשי רק לאחר שהתייצבה — בהתאם לנוהגי הפיתוח של מערכות מבוזרות

.[5]ומיקרו-שירותים

גרסת ההגשה הסופית אינה מסומנת ב״מצב הענף האחרון״ העמום, אלא (.התג מקפיא נקודתAnnotated Git Tagמתועד ) Git מקובעת באמצעות תג זמן ודאית ובלתי ניתנת לערעור בהיסטוריית המאגר, ומאפשר לבוחן לשחזר במדויק את הקוד שהוגש — ולא גרסה מאוחרת יותר שאולי נכתבה לאחר

תום המועד.

---

<!-- source-pdf-page: 134 -->

### תיוג גרסת ההגשה

```shell
# Create an annotated, documented tag for the submission commit.
# The -a flag makes it an annotated tag (stored as a full object),
# and -m attaches the mandatory documentation message.
git tag -a v1.0-submission -m "Final submission: Police-Thief P2P, group N"

# Push the tag to the remote the grader can access
# (public, or private shared with the lecturer).
git push origin v1.0-submission

# (Optional) verify the tag was created and points to the right commit.
git show v1.0-submission
```

התג `v1.0-submission` הופך את הקומיט הנבחר לנקודת ייחוס יציבה. שימו לב שמדובר בקטע פקודות מעטפת (`shell`), שבו ההערות באנגלית בלבד — כמקובל בכל ההנחיות התפעוליות שבספר זה.

### The Academic README Re README.md הדוח האקדמי: 2
### port
README.md לב ההגשה התיעודית הוא דוח אקדמי מורחב הכתוב בקובץ אין זה קובץ הוראות התקנה בלבד, אלא מסמך מדעי שבשורש המאגר. המסביר את ההחלטות התכנוניות, מנמק אותן, ומציג את הראיות האמפיריות להצלחתן.

**9 מוגדר בפרק READMEתוכן ה-**

**שני** של הדוח האקדמי — חמשת מרכיביו, לצד דרישת _תוכן החובה_ 9 )שוטר וגנב( והקישור הצולב ביניהם — מוגדר במלואו בפרק **המאגרים** ודאו שכל המרכיבים :מבנה, תוכן ושני מאגרים״(.GitHub)״הגשה ב- משני המאגרים. _כל אחד_ של README.mdקיימים בקובץ ה-

---

<!-- source-pdf-page: 135 -->

הדרישה לצילומי המסך אינה פורמלית בלבד: מפת האמונות מוכיחה שהסוכן Verified והחיווי אכן מנהל הסקה הסתברותית תחת תצפית חלקית, (של המשחק נשמרה — ששרשרת המהלכיםIntegrityמוכיח שההגינות ) OK המוצפנת נבדקה ואומתה, בדומה למנגנוני הוכחה קריפטוגרפיים המבססים .[20]אמון ללא צורך בגורם מרכזי מהימן

### לעולם אין להעלות סודות למאגר
, כל קובץ שיועלה אליו גלוי לעולם כולו; וגם אם הוא _ציבורי_ אם המאגר — עדיין חל איסור מוחלט להעלות פרטי _פרטי ומשותף עם המרצה בלבד_ OAuth של token.jsonוcredentials.json הזדהות ואסימוני גישה — ובכללם (. חובה ב( וכל מפתח או סוד תצורה )ראו נספח התצורה א)ראו נספח המחריג במפורש קבצים אלה, כך .gitignore לכלול בשורש המאגר קובץ שלא ייכללו בקומיט בטעות. סוד שהודלף פעם אחת נחשב חשוף לצמיתות .Git— גם אם יימחק בקומיט מאוחר יותר, הוא נותר בהיסטוריית ה-

---

<!-- source-pdf-page: 136 -->

### Submission Checklist רשימת התיוג להגשה 3
יש לוודא שכל פריט עומד בסטטוס הטבלה שלהלן מרכזת את תנאי הסף. הנדרש טרם יצירת תג ההגשה.

:רשימת תיוג ההגשה6 טבלה

|**סטטוס נדרש**|**פריט**|
|---|---|
|ציבוריים_או_פרטיים<br>ומשותפים עם המרצה|שני מאגריGitHubנגישים למרצה<br>)שוטר, גנב(|
|קיימים|קישור צולב בין המאגרים+שני<br>קישורים בהגשה|
|v1.0submission<br>נדחף|תגGitמתועד לגרסת ההגשה|
|שלמים בשני המאגרים|מרכיבי הדוח ב-<br>README.md<br>)פרק9<br>(|
|מצורפים|צילומי מסך של מפת האמונות<br>)GUI<br>(|
|מצורף|צילום מסךReplayעם<br>Verified OK|
|2ומעלה|לפחות שני משחקים מול קבוצות<br>שונות|
|שני הצדדים שלחו|דוא״ל סיום משחק — כל קבוצה<br>בנפרד|
|מאומת|אין סודות שהועלו למאגר<br>)<br>.gitignore<br>(|

---

<!-- source-pdf-page: 137 -->

### פיתוח מערכות, לא רק תכנות
זכרו את המסר החורז את הספר כולו: הפרויקט שלפניכם איננו מטלת תכנות גרידא, כי אם תרגיל בפיתוח מערכות מורכב תחת תנאי רשת Co ) _תיאום_ ההצלחה נמדדת בארבעה מדדים מרכזיים — אמיתיים. לאי-ודאות באמצעות שובלי עקבות _הסתגלות_ (בין הסוכנים;ordination (בעזרת מנגנוני גיבובIntegrity ) _הגינות_ ;הבטחת[14]מבוססי סטיגמרגיה Gatekeeper קוד נכונה )תבניות _ארכיטקטורת_ ;ודבקות ב[20]מתקדמים .ארבעה מדדים אלה — ולא יופיו של אלגוריתם בודד —[5] (Orchestratorוהם שיקבעו את הצלחת כל קבוצה ואת יכולתה להתמודד בעולם האמיתי של מערכות בינה מלאכותית מבוזרות. סיכום מלא של מדדים אלה מובא .11 בפרק פרק

---

[← Appendix B — Unified Configuration](appendix-b-unified-configuration.md) · [Contents](README.md) · [Appendix D — Reference Code Repository →](appendix-d-reference-code.md)
