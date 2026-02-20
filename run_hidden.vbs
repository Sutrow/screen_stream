' run_hidden.vbs
' Запускает клиент абсолютно незаметно: без окна консоли и без иконки в панели задач.
' Двойной клик на этом файле → клиент запустится в фоне.

Dim WShell
Set WShell = CreateObject("WScript.Shell")

' Измените путь если нужно:
ScriptPath = WShell.CurrentDirectory & "\client.py"

WShell.Run "pythonw """ & ScriptPath & """", 0, False

Set WShell = Nothing