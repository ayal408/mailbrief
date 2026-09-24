# שחרור גרסה חדשה

## ביום-יום

כל `git push` ל-main מריץ ב-GitHub את הבדיקות (pyflakes + כל הטסטים, על Windows).
✅ ירוק = הכול תקין · ❌ אדום = משהו נשבר — הפירוט בלשונית **Actions**.

## גרסה חדשה — פקודה אחת

```powershell
.\release.ps1 1.2.0
```

הסקריפט בודק שאין שינויים לא שמורים, מריץ את הבדיקות, מעדכן את מספר הגרסה בקוד, ודוחף תגית `v1.2.0`.
משם GitHub Actions עושה לבד (כ-5 דקות):

1. בודק שהתגית תואמת לגרסה בקוד
2. מריץ שוב את הבדיקות
3. בונה `MailBrief.exe` עם האייקון
4. יוצר Release עם הקובץ ורשימת השינויים (מתוך הקומיטים)
5. שולח את הגרסה ל-winget

מי שהוריד ידנית יקבל בתוכנה „✨ עדכון עכשיו”; מי שהתקין ב-winget — `winget upgrade mailbrief`.

**מספרי גרסה:** תיקון קטן `1.1.0 → 1.1.1` · תכונה חדשה `1.1.0 → 1.2.0` · שינוי גדול `1.x → 2.0.0`.

## הגדרה חד-פעמית ל-winget

השלב של winget צריך הרשאה לפתוח בשמך בקשת עדכון ב-`microsoft/winget-pkgs`
(ורק אחרי שהגרסה הראשונה, 1.1.0, אושרה שם):

1. GitHub ← Settings ← Developer settings ← **Personal access tokens (classic)** ← Generate new token
2. שם: `winget`, תוקף: שנה, הרשאה: **public_repo** בלבד
3. בריפו: Settings ← Secrets and variables ← Actions ← New repository secret ← שם **`WINGET_TOKEN`**, להדביק את הטוקן

בלי הסוד הזה הכול עובד חוץ משליחה ל-winget (מופיעה הודעה ב-Actions, והגרסה עדיין יוצאת ב-GitHub).

## אם משהו נכשל

- **❌ בבדיקות** — הפירוט ב-Actions; מתקנים, `git push`, ומריצים שוב `release.ps1` עם אותו מספר (התגית לא נוצרה).
- **❌ אחרי שהתגית נדחפה** — מתקנים ומשחררים את המספר הבא (`1.2.1`). לא מוחקים גרסה שכבר יצאה — winget ומשתמשים כבר מסתמכים עליה.

## The built-in Google key

MailBrief.exe can carry its own Google sign-in key, so users just click "Connect with Google" with no Google Cloud setup.
The key is never in git: `google_client.json` is git-ignored, and release builds read it from the `GOOGLE_CLIENT_JSON`
repository secret.

1. In MailBrief -> Settings -> "Google one-time setup", save the Client ID and secret of the MailBrief project
   (a **Desktop app** client; in Google Auth Platform -> Audience the app must be **In production**).
2. Run `powershell -ExecutionPolicy Bypass -File set-google-key.ps1`: it writes `google_client.json` for local builds
   and sets the GitHub secret. The key is not printed.
3. The next `build.ps1` / release includes it ("Built-in Google key: yes" in the log).

Until Google verifies the app, users see "Google hasn't verified this app" (Advanced -> Go to MailBrief), and at most
100 users can connect. A user's own key in the settings always wins over the built-in one.
