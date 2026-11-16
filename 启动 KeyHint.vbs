' KeyHint launcher - 自动寻找装了 Pillow 的 Python，静默启动。
' 不写死任何本机路径：先查 PATH，再查 %LOCALAPPDATA% 默认安装位置，最后试 py launcher。
Option Explicit
Dim fso, sh, here, bases, i, base, pexe, pyw, rc, launched, localBase
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here

localBase = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python310\")
bases = Array("", localBase)

launched = False
For i = 0 To UBound(bases)
    base = bases(i)
    pexe = base & "python.exe"
    pyw = base & "pythonw.exe"
    If base = "" Or fso.FileExists(pexe) Then
        rc = 1
        On Error Resume Next
        rc = sh.Run("""" & pexe & """ -c ""import PIL""", 0, True)
        If Err.Number <> 0 Then rc = 1
        Err.Clear
        On Error GoTo 0
        If rc = 0 Then
            sh.Run """" & pyw & """ app.py", 0, False
            launched = True
            Exit For
        End If
    End If
Next

' 兜底：Windows Python Launcher
If Not launched Then
    rc = 1
    On Error Resume Next
    rc = sh.Run("py -3 -c ""import PIL""", 0, True)
    If Err.Number <> 0 Then rc = 1
    Err.Clear
    On Error GoTo 0
    If rc = 0 Then
        sh.Run "py -3w app.py", 0, False
        launched = True
    End If
End If

If Not launched Then
    MsgBox "KeyHint 启动失败：没找到装了 Pillow 的 Python。" & vbCrLf & _
           "请执行 pip install pillow 后重试。", 16, "KeyHint"
End If
