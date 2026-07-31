# Appendix B — Unified Configuration

> **Source:** [Distributed Cops-and-Robbers over a Peer-to-Peer Network, v3.0.0](https://github.com/rmisegal/Game-P2P-Cop-Chase/blob/master/docs/police_thief_p2p.pdf)
> **Physical PDF pages:** 126–132
> **Source SHA-256:** `7c9e1d7527582c3aef9afd71709981cea50ea60b8fabefe85efccab0a5fdd02e`
>
> Curated Markdown transcription for repository-local study. The source PDF remains authoritative; Appendix F is the sole authority for binding quantitative parameters. Hebrew/English bidirectional text, equations, and complex visual layouts may render differently from the PDF.
>
> Copyright © 2026 Dr. Yoram Segal / Gal Technologies Artificial Intelligence Ltd. All rights reserved. Authorized educational use only under the source terms; no commercial use or redistribution.

[← Appendix A — Gmail API and OAuth 2.0](appendix-a-gmail-api-oauth.md) · [Contents](README.md) · [Appendix C — GitHub Submission and Academic Report →](appendix-c-github-submission.md)

---

<!-- source-pdf-page: 126 -->

## נספח ב — תצורה אחידה לקובץ ההגדרות
### Why a מדוע חוקה משותפת? קובץ תצורה בעולם ללא שופט 1 Shared Constitution?
,שבו שני הסוכנים מתעמתים ישירות ללא שרת מרכזיP2P במשחק מבוזר מסוג המשמש שופט, נולדת שאלה יסודית: מי קובע את חוקי הפיזיקה של המשחק? כאשר קיים שרת מרכזי, הוא לבדו אוכף את גודל הגריד, את מספר המהלכים המרבי ואת קצב התפוגגות הריח, ושני השחקנים כפופים לפסיקתו. אך בהיעדר שופט, כל צד מריץ עותק משלו של לוגיקת המשחק — ואם שני העותקים אינם מסכימים על אותם ערכים בדיוק, המרוץ מתפרק לשתי מציאויות סותרות

שאינן ניתנות ליישוב.

למקור אמת _תנאי המשחק המוסכמים_ הפתרון המעשי הוא להפוך את כל — של **החוקה החתומה** config/game.json יחיד, קריא וגלוי, המרוכז בקובץ שאליה שני _חוקה_ קובץ זה איננו רק אוסף של קבועים; הוא ה המשחק. הצדדים מסכימים בטרם יורד המסך, והוא נטען בזהות בייט-אחר-בייט בשני con — _פרטי_ הקצוות ונעול בחתימה קריפטוגרפית. לצדו מחזיק כל עמית קובץ —ובו הגדרותיו המקומיות בלבד )פורט הרשת, בחירת מודול fig/game.toml האסטרטגיה, מצב מודל השפה למשחק המילולי, יעד הדוא״ל וזהות הקבוצה(, שאינן נתונות למשא ומתן ואינן חייבות להיות זהות בין הצדדים. כאשר קיים (על ערכי אותם מפתחות בקובץoverlay ) _גוברים_ המשותף, ערכיו JSONקובץ ה- הפרטי, כך ששני הסוכנים אוכפים את אותה פיזיקה בדיוק: אותו TOMLהכך, אף על פי שאין ישות שלישית לוח, אותם גבולות, אותו קצב דעיכה. שתפסוק, שני הצדדים מחשבים את אותה תוצאה מתוך אותם כללים.

---

<!-- source-pdf-page: 127 -->

(.הפרדת הפרמטריםConfigurabilityיתרון נוסף הוא הקריאוּת וההגדרוּת ) מן הקוד מאפשרת לשנות את תנאי הקרב — גריד גדול יותר, מגבלת זמן נוקשה יותר, שדה ריח רחב יותר — מבלי לגעת בשורת קוד אחת של לוגיקה. של הספר, וכל אחד מהם _ברירות המחדל המוסכמות_ הערכים המוצגים כאן הם (,כל עוד שני הצדדים טוענים אתpermatchניתן לכיוונון מחדש בכל מפגש ) מצורפת לספר JSON .דוגמה מלאה של התצורה בפורמטJSON אותו קובץ (. ו )ראו טבלת המשתנים בנספח **]** קובץ התצורה **[** כקובץ

### When JSON, When TOML, —ולמה TOML ומתי JSON מתי 2
### and Why
ולכל אחד תפקיד מובחן. הפרויקט משתמש בשני פורמטים של תצורה, **;כלJSON כל מה ששני הצדדים חייבים להסכים עליו נכתב ב-** ההבחנה פשוטה: **.TOMLמה שהוא פרטי ומקומי לעמית יחיד נכתב ב-** - בפורמט זה כתובים )א( **—לנתונים משותפים, חתומים ומוחלפים. JSON** _ארבעת הקבצים_ )ב( ;config/game.json של המשחק — _התנאים המוסכמים_ (;ו-9 — ההצהרה, התצורה, היומן ודוח התוצאות )פרק _הסטנדרטיים_ נבחר משום שהוא JSON .rate_limits.json )ג( תצורת מגביל-הקצב — )מפתחות ממוינים( _קנונית_ , ניתן לסריאליזציה _תקן חד-משמעי וחוצה-שפות_ (,ומתאים לזהות בייט-אחר-בייט,config_sha256 עקבי ) _גיבוב_ ולכן ל לחתימה קריפטוגרפית ולהחלפה בין מכונות ובין צוותים שאולי כתבו את — חייב _רואה, מאמת או תלוי בו_ הקוד בשפות שונות. כל דבר שהיריב

להיות כאן.

- _אך ורק_ בפורמט זה כתוב **—לתצורה פרטית ומקומית בלבד. TOML** :פורט הרשת, כתובתconfig/game.toml הקובץ הפרטי לכל עמית — ,LLMהיריב, בחירת מודול האסטרטגיה, מצב מודל השפה, הגדרות ה- על ידי _ביד_ נבחר משום שהוא נערך TOML הדוא״ל וזהות הקבוצה. — יתרון מכריע, שכן מקטעי _תומך בהערות_ כל צוות, קריא במיוחד, ו כוללים הסברי-קוד המדריכים את [trash_talk]ו[strategy] ואינו נחתם, ולכן אינו זקוק _אינו חוצה את הרשת_ קובץ זה הסטודנט. ; **שום ערך הרלוונטי ליריב אינו נמצא בו** לצורה קנונית או ניתנת-לגיבוב. .JSONאם ערך כלשהו הופך למשותף — מקומו עובר ל-

---

<!-- source-pdf-page: 128 -->

שאלו ״האם היריב חייב להסכים לערך הזה, או להסתמך עליו?״ _מבחן ההכרעה:_ הפרטי. TOMLהמשותף; אם לא, הוא נשאר ב- JSON— אם כן, מקומו ב-

### The Signed Shared File הקובץ המשותף החתום 3
הלוח והסוכנים על מקטעיו: config/game.json המשותף _חוקה_ להלן קובץ ה movement_and_barri(,התנועה והמחסומים )board_and_agents) net(,הרשת והליגה )pheromones(,הפרומונים )scoring(,הניקוד )ers (.שניrate_limiter_gatekeeper(ומגביל-הקצב )work_and_league , וחילופי החתימה שלפני המשחק _זהה בייט-אחר-בייט_ העמיתים טוענים עותק מסרבים לשחק בכל אי-התאמה. הערכים כאן הם ברירות המחדל המחייבות

(. ושל הספר )ראו הטבלה המחייבת בנספח

---

<!-- source-pdf-page: 129 -->

### הקובץ `config/game.json` (התנאים החתומים המשותפים) — חלק 1

```json
{
  "schema_version": "1.2",
  "agreed_between": ["group-a", "group-b"],
  "board_and_agents": {
    "grid_size": 7,
    "num_agents": 2,
    "thief_start": [3, 3],
    "cop_start": [0, 0],
    "axis_origin_corner": "top-left",
    "axis_start_index": 0
  },
  "world": {
    "map_area": "New York",
    "hint_max_words": 15
  },
  "movement_and_barriers": {
    "move_set": ["N", "S", "E", "W", "STAY"],
    "max_barriers": 14,
    "max_moves": 35,
    "survival_threshold": 35
  },
  "scoring": {
    "capture_cop": 20,
    "capture_thief": 5,
    "survival_cop": 5,
    "survival_thief": 10,
    "tie_score": 2,
    "technical_loss": 0
  },
  "pheromones": {
    "pheromone_center_intensity": 0.9,
    "pheromone_decay": 0.10,
    "pheromone_grid_size": 5
  },
  "network_and_league": {
    "response_timeout_sec": 30,
    "watchdog_timeout_sec": 60,
    "num_games": 1,
    "diversity_reward": 10,
    "min_games_to_pass": 2,
    "max_games_per_team": 10,
    "token_budget_per_series": 200000
```

> The JSON object continues on physical source page 130.

---

<!-- source-pdf-page: 130 -->

### הקובץ `config/game.json` — חלק 2

```json
  },
  "rate_limiter_gatekeeper": {
    "requests_per_minute": 30,
    "concurrent_requests": 2,
    "retry_backoff_sec": 5,
    "max_retries": 3,
    "queue_depth": 100
  }
}
```

שדות המפתח תואמים אחד־לאחד לטבלת הפרמטרים המחייבת: `grid_size` = **[גודל הלוח]**, `max_barriers` = **[מכסת המחסומים]**, `scoring.capture_cop` = **[ניקוד לכידה – שוטר]**, וכן הלאה. ערך כל שדה עשוי להשתנות במשא ומתן (בכיוון המחמיר בלבד עבור פרמטר מסוג ״מינימום״), אך *שמות* השדות קבועים ומחייבים. שדה `num_games` נשלח כברירת מחדל בערך 1 (משחקון־דוגמה יחיד); סדרת הליגה המלאה דורשת **[מספר המשחקונים]** משחקונים.

### 4. הקובץ הפרטי לכל עמית / The Private Per-Peer File

לצד ה־JSON המשותף מחזיק כל עמית `config/game.toml` משלו — פרטי, מקומי, ואינו נתון למשא ומתן. הוא מכיל את זהות הקבוצה, פורט הרשת וכתובת היריב, בחירת מודול האסטרטגיה (`[strategy]`), מצב מודל השפה למשחק המילולי (`[trash_talk]`), הגדרות מודל השפה (`[llm]`), יעד הדוא״ל וההגדרות הגרפיות. להלן שלד מקוצר:

---

<!-- source-pdf-page: 131 -->

### הקובץ `config/game.toml` (פרטי לכל עמית — קטע נבחר)

```toml
version = "1.10"

[game]
group_name = "My-Team"
group_id = "my-team"
sub_game_number = 1
members = ["id-1001", "id-1002"]
repos = { cop = "https://github.com/you/repo", thief = "https://github.com/you/repo" }

[network]
my_port = 8802  # MY MCP server port
opponent_url = "http://127.0.0.1:8801/mcp"  # the only thing I know about the opponent
turn_timeout_seconds = 180

# [strategy] -- optional: point at YOUR brain subclass
# (else the shipped heuristic runs)
# thief_class = "my_team.strategy:MyThiefBrain"
# police_class = "my_team.strategy:MyPoliceBrain"

# [trash_talk] -- optional: HOW the banter is produced.
# The MOVE is always pure Python.
# provider = "template"
# template (0 tokens, default) | ollama | claude_api | claude_cli

[llm]
model = "claude-opus-4-8[1m]"  # MY choice; the opponent may differ
step_deadline_seconds = 30     # hard cap on LLM thinking per step

[email]
recipient = "rmisegal+uoh26finalgame@gmail.com"
mode = "draft"
```

---

<!-- source-pdf-page: 132 -->

שבו גוברים על כל מפתח _תנאי המשחק_ ,ערכיconfig/game.json כאשר קיים —כך שהקובץ הפרטי לעולם אינו יכול ״להחליש״ תנאי חתום. TOMLמקביל ב- — שמו, משמעותו וערכו — מרוכז בטבלת **המילון המלא והמחייב של כל פרמטר** . והפרמטרים המחייבת שבנספח

---

[← Appendix A — Gmail API and OAuth 2.0](appendix-a-gmail-api-oauth.md) · [Contents](README.md) · [Appendix C — GitHub Submission and Academic Report →](appendix-c-github-submission.md)
