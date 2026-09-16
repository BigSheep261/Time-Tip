!include "MUI2.nsh"
!include "x64.nsh"
Name "Time-Tip Service"
OutFile "Time-Tip-Service-Setup.exe"
InstallDir "C:\Time-Tip-BackEnd"
RequestExecutionLevel admin
SetCompressor /SOLID lzma
ShowInstDetails show
ShowUninstDetails show
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\ProgramData\config\initial-login.txt"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Show initial login information"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "Windows x64 is required."
    Abort
  ${EndIf}
  SetRegView 64
FunctionEnd
Section
  SetShellVarContext all
  IfFileExists "$INSTDIR\service_core\TimeTipService.exe" 0 copy_files
  ExecWait '"$INSTDIR\service_core\TimeTipService.exe" stop' $0
  IntCmp $0 0 copy_files install_failed install_failed
copy_files:
  SetOutPath "$INSTDIR\service_core"
  File /r "build\dist\TimeTipCore\*.*"
  File "build\TimeTipService.exe"
  SetOutPath "$INSTDIR\backend_web\dist"
  File /r "..\backend_web\dist\*.*"
  SetOutPath "$INSTDIR"
  CreateDirectory "$INSTDIR\ProgramData\database"
  CreateDirectory "$INSTDIR\ProgramData\packages\manual"
  CreateDirectory "$INSTDIR\ProgramData\logs"
  ExecWait '"$INSTDIR\service_core\TimeTipCore.exe" --init-config' $0
  IntCmp $0 0 register_service install_failed install_failed
register_service:
  ExecWait '"$INSTDIR\service_core\TimeTipService.exe" install' $0
  IntCmp $0 0 configure_service install_failed install_failed
configure_service:
  nsExec::ExecToLog '"$SYSDIR\sc.exe" failure TimeTipService reset= 86400 actions= restart/5000/restart/15000/restart/60000'
  Pop $0
  nsExec::ExecToLog '"$SYSDIR\sc.exe" sdset TimeTipService D:(A;;CCLCSWRPWPDTLOCRRC;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)(A;;CCLCSWRPWPLOCRRC;;;BU)'
  Pop $0
  ExecWait '"$INSTDIR\service_core\TimeTipService.exe" start' $0
  IntCmp $0 0 shortcuts install_failed install_failed
shortcuts:
  CreateShortCut "$DESKTOP\Time-Tip Service.lnk" "$INSTDIR\service_core\TimeTipService.exe" "start"
  CreateDirectory "$SMPROGRAMS\Time-Tip Service"
  CreateShortCut "$SMPROGRAMS\Time-Tip Service\Start Service.lnk" "$INSTDIR\service_core\TimeTipService.exe" "start"
  CreateShortCut "$SMPROGRAMS\Time-Tip Service\Stop Service.lnk" "$INSTDIR\service_core\TimeTipService.exe" "stop"
  CreateShortCut "$SMPROGRAMS\Time-Tip Service\Restart Service.lnk" "$INSTDIR\service_core\TimeTipService.exe" "restart"
  WriteUninstaller "$INSTDIR\uninstall.exe"
  CreateShortCut "$SMPROGRAMS\Time-Tip Service\Uninstall.lnk" "$INSTDIR\uninstall.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\TimeTipService" "DisplayName" "Time-Tip Service"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\TimeTipService" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\TimeTipService" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\TimeTipService" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\TimeTipService" "NoRepair" 1
  Goto installed
install_failed:
  MessageBox MB_ICONSTOP "Installation failed (code $0). Check ProgramData\logs\service.log. Existing configuration and data are preserved."
  SetErrorLevel 1
  Abort
installed:
SectionEnd
Section "Uninstall"
  SetShellVarContext all
  SetRegView 64
  ExecWait '"$INSTDIR\service_core\TimeTipService.exe" uninstall' $0
  IntCmp $0 0 remove_files uninstall_failed uninstall_failed
remove_files:
  Delete "$DESKTOP\Time-Tip Service.lnk"
  RMDir /r "$SMPROGRAMS\Time-Tip Service"
  Delete "$INSTDIR\service_core\TimeTipCore.exe"
  Delete "$INSTDIR\service_core\TimeTipService.exe"
  RMDir /r "$INSTDIR\service_core\_internal"
  RMDir /r "$INSTDIR\backend_web\dist"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\TimeTipService"
  Delete "$INSTDIR\uninstall.exe"
  Goto removed
uninstall_failed:
  MessageBox MB_ICONSTOP "Could not stop/remove the service. Uninstallation was aborted; data is preserved."
  SetErrorLevel 1
  Abort
removed:
SectionEnd
