# Expected privacy settings for this laptop (Windows 11 Home + Microsoft 365 apps).
# privacy-settings.ps1 applies these and checks them weekly for drift.
#
# Prefer policy keys (Software\Policies\...): feature updates reset the ordinary
# Settings toggles far more often than they touch policies. The ordinary toggles are
# set as well so the Settings app shows the same state.
#
# Only settings Windows Home actually honors are listed; Enterprise/Education-only
# policies would just give false reassurance.
@{
    Registry = @(
        # ---- Settings > Privacy & security > General
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo'; Name = 'Enabled'; Value = 0; Why = 'Advertising ID off' }
        @{ Path = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\AdvertisingInfo'; Name = 'DisabledByGroupPolicy'; Value = 1; Why = 'Advertising ID off (policy)' }
        @{ Path = 'HKCU:\Control Panel\International\User Profile'; Name = 'HttpAcceptLanguageOptOut'; Value = 1; Why = 'Websites cannot read the language list' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced'; Name = 'Start_TrackProgs'; Value = 0; Why = 'No app-launch tracking' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer'; Name = 'NoInstrumentation'; Value = 1; Why = 'No app-launch tracking (policy)' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'; Name = 'SubscribedContent-338393Enabled'; Value = 0; Why = 'No suggested content in Settings' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'; Name = 'SubscribedContent-353694Enabled'; Value = 0; Why = 'No suggested content in Settings' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'; Name = 'SubscribedContent-353696Enabled'; Value = 0; Why = 'No suggested content in Settings' }

        # ---- Speech, inking & typing
        @{ Path = 'HKCU:\Software\Microsoft\Speech_OneCore\Settings\OnlineSpeechPrivacy'; Name = 'HasAccepted'; Value = 0; Why = 'Online speech recognition off' }
        @{ Path = 'HKCU:\Software\Microsoft\InputPersonalization'; Name = 'RestrictImplicitInkCollection'; Value = 1; Why = 'Inking & typing personalization off' }
        @{ Path = 'HKCU:\Software\Microsoft\InputPersonalization'; Name = 'RestrictImplicitTextCollection'; Value = 1; Why = 'Inking & typing personalization off' }
        @{ Path = 'HKCU:\Software\Microsoft\InputPersonalization\TrainedDataStore'; Name = 'HarvestContacts'; Value = 0; Why = 'Inking & typing personalization off' }
        @{ Path = 'HKCU:\Software\Microsoft\Personalization\Settings'; Name = 'AcceptedPrivacyPolicy'; Value = 0; Why = 'Inking & typing personalization off' }
        @{ Path = 'HKLM:\SOFTWARE\Policies\Microsoft\InputPersonalization'; Name = 'AllowInputPersonalization'; Value = 0; Why = 'Inking & typing personalization off (policy)' }
        @{ Path = 'HKCU:\Software\Microsoft\Input\TIPC'; Name = 'Enabled'; Value = 0; Why = 'Improve inking and typing off' }

        # ---- Diagnostics & feedback (Home can't go below Required)
        @{ Path = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\DataCollection'; Name = 'AllowTelemetry'; Value = 1; Why = 'Diagnostic data: Required only' }
        @{ Path = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\DataCollection'; Name = 'DoNotShowFeedbackNotifications'; Value = 1; Why = 'Feedback prompts off' }
        @{ Path = 'HKCU:\Software\Microsoft\Siuf\Rules'; Name = 'NumberOfSIUFInPeriod'; Value = 0; Why = 'Feedback frequency: never' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Privacy'; Name = 'TailoredExperiencesWithDiagnosticDataEnabled'; Value = 0; Why = 'Tailored experiences off' }
        @{ Path = 'HKCU:\Software\Policies\Microsoft\Windows\CloudContent'; Name = 'DisableTailoredExperiencesWithDiagnosticData'; Value = 1; Why = 'Tailored experiences off (policy)' }

        # ---- Activity history
        @{ Path = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\System'; Name = 'EnableActivityFeed'; Value = 0; Why = 'Activity history off' }
        @{ Path = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\System'; Name = 'PublishUserActivities'; Value = 0; Why = 'Activity history off' }
        @{ Path = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\System'; Name = 'UploadUserActivities'; Value = 0; Why = 'Activity history not uploaded' }

        # ---- Search
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\SearchSettings'; Name = 'IsMSACloudSearchEnabled'; Value = 0; Why = 'Search: no Microsoft-account cloud content' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\SearchSettings'; Name = 'IsAADCloudSearchEnabled'; Value = 0; Why = 'Search: no work/school cloud content' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\SearchSettings'; Name = 'IsDeviceSearchHistoryEnabled'; Value = 0; Why = 'Search history off' }
        @{ Path = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Windows Search'; Name = 'AllowCloudSearch'; Value = 0; Why = 'Search: no cloud content (policy)' }
        @{ Path = 'HKCU:\Software\Policies\Microsoft\Windows\Explorer'; Name = 'DisableSearchBoxSuggestions'; Value = 1; Why = 'Start search does not send queries to Bing' }

        # ---- Recent files: Start, Explorer, Jump Lists
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced'; Name = 'Start_TrackDocs'; Value = 0; Why = 'No recent files in Start / Jump Lists' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer'; Name = 'NoRecentDocsHistory'; Value = 1; Why = 'No recent-files history (policy)' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer'; Name = 'ClearRecentDocsOnExit'; Value = 1; Why = 'Recent-files list cleared at sign-out (policy)' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer'; Name = 'ShowRecent'; Value = 0; Why = 'Explorer Home: no recent files' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer'; Name = 'ShowFrequent'; Value = 0; Why = 'Explorer Home: no frequent folders' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer'; Name = 'ShowCloudFilesInQuickAccess'; Value = 0; Why = 'Explorer Home: no cloud files' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced'; Name = 'Start_IrisRecommendations'; Value = 0; Why = 'Start: no tips / app recommendations' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced'; Name = 'Start_AccountNotifications'; Value = 0; Why = 'Start: no account notifications' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced'; Name = 'ShowSyncProviderNotifications'; Value = 0; Why = 'Explorer: no OneDrive/M365 ads' }

        # ---- Tips, suggestions, silently installed apps
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'; Name = 'SubscribedContent-338388Enabled'; Value = 0; Why = 'Start: no suggestions' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'; Name = 'SubscribedContent-338389Enabled'; Value = 0; Why = 'No tips and suggestions' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'; Name = 'SubscribedContent-310093Enabled'; Value = 0; Why = 'No Windows welcome experience' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'; Name = 'SystemPaneSuggestionsEnabled'; Value = 0; Why = 'Start: no suggestions' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'; Name = 'SilentInstalledAppsEnabled'; Value = 0; Why = 'No silently installed sponsored apps' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'; Name = 'SoftLandingEnabled'; Value = 0; Why = 'No tips about Windows' }
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\UserProfileEngagement'; Name = 'ScoobeSystemSettingEnabled'; Value = 0; Why = 'No "finish setting up your device" nags' }
        @{ Path = 'HKCU:\Software\Policies\Microsoft\Windows\WindowsCopilot'; Name = 'TurnOffWindowsCopilot'; Value = 1; Why = 'Windows Copilot off (policy)' }

        # ---- Office (Microsoft 365 apps). Policy keys; Office re-reads them at every start.
        @{ Path = 'HKCU:\Software\Policies\Microsoft\Office\16.0\Common\Privacy'; Name = 'usercontentdisabled'; Value = 2; Why = 'Office: connected experiences that analyze content OFF (Copilot, Editor, Designer, translate)' }
        @{ Path = 'HKCU:\Software\Policies\Microsoft\Office\16.0\Common\Privacy'; Name = 'downloadcontentdisabled'; Value = 2; Why = 'Office: connected experiences that download online content OFF' }
        @{ Path = 'HKCU:\Software\Policies\Microsoft\Office\16.0\Common\Privacy'; Name = 'controllerconnectedservicesenabled'; Value = 2; Why = 'Office: optional connected experiences OFF' }
        @{ Path = 'HKCU:\Software\Policies\Microsoft\Office\Common\ClientTelemetry'; Name = 'SendTelemetry'; Value = 3; Why = 'Office: diagnostic data Neither' }
        @{ Path = 'HKCU:\Software\Policies\Microsoft\Office\16.0\Common'; Name = 'LinkedIn'; Value = 0; Why = 'Office: LinkedIn features off' }
        @{ Path = 'HKCU:\Software\Policies\Microsoft\Office\16.0\Common\Feedback'; Name = 'Enabled'; Value = 0; Why = 'Office: feedback off' }
        @{ Path = 'HKCU:\Software\Policies\Microsoft\Office\16.0\Common\Feedback'; Name = 'SurveyEnabled'; Value = 0; Why = 'Office: surveys off' }
        @{ Path = 'HKCU:\Software\Microsoft\Office\16.0\Common\General'; Name = 'PreferCloudSaveLocations'; Value = 0; Why = 'Office: save to this computer by default' }
    )

    # Apps that must stay uninstalled (Store packages). Windows updates like to bring these back.
    ForbiddenPackages = @(
        @{ Name = 'Microsoft.OutlookForWindows'; Why = 'New Outlook routes non-Microsoft mailboxes through Microsoft''s cloud' }
        @{ Name = 'Microsoft.Copilot'; Why = 'Copilot app' }
    )

    # Classic installs that must stay gone (checked by path).
    ForbiddenPaths = @(
        @{ Path = 'C:\Program Files\Microsoft OneDrive'; Why = 'OneDrive was retired 2026-10-10' }
        @{ Path = '%LOCALAPPDATA%\Microsoft\OneDrive\OneDrive.exe'; Why = 'OneDrive (per-user install) was retired 2026-10-10' }
    )
}
