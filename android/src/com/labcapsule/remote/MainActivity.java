package com.labcapsule.remote;

import android.Manifest;
import android.animation.ValueAnimator;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.DownloadManager;
import android.bluetooth.*;
import android.bluetooth.le.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.graphics.*;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.*;
import android.provider.OpenableColumns;
import android.provider.Settings;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import android.view.*;
import android.widget.*;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.ArrayList;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.zip.CRC32;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

public class MainActivity extends Activity {
    private static final String APP_VERSION = "0.6.0";
    private static final String REPOSITORY = "81823650800wzy-sketch/LabCapsule";
    private static final String WIFI_GUIDE_URL = "https://github.com/" + REPOSITORY +
            "/blob/main/docs/V0.3.3_BLE_WIFI_QUICKSTART_ZH.md";
    private static final String V040_GUIDE_URL = "https://github.com/" + REPOSITORY +
            "/blob/main/docs/V0.4.0_EXPERIMENT_GIF_GUIDE_ZH.md";
    private static final String V060_GUIDE_URL = "https://github.com/" + REPOSITORY +
            "/blob/main/docs/V0.6.0_IDLE_GIF_MODE_GUIDE_ZH.md";
    private static final int REQUEST_FIRMWARE = 1001, REQUEST_MEDIA = 1002,
            REQUEST_BLE_PERMISSIONS = 1003, REQUEST_NOTIFICATION_PERMISSION = 1004,
            REQUEST_CSV = 1005;

    private static final UUID SERVICE_UUID = uuid(1), COMMAND_UUID = uuid(2),
            STATUS_UUID = uuid(3), OTA_CONTROL_UUID = uuid(4), OTA_DATA_UUID = uuid(5),
            FILE_CONTROL_UUID = uuid(6), FILE_DATA_UUID = uuid(7),
            EXPERIMENT_DATA_UUID = uuid(8);
    private static UUID uuid(int id) {
        return UUID.fromString(String.format(Locale.US,
                "6c4300%02d-4c61-6243-6170-73756c650001", id));
    }

    private static int INK = Color.rgb(247, 243, 224), MUTED = Color.rgb(169, 166, 151),
            BLUE = Color.rgb(246, 216, 14), GREEN = Color.rgb(77, 220, 143),
            RED = Color.rgb(255, 76, 68), CANVAS = Color.rgb(14, 14, 15),
            PANEL = Color.rgb(25, 25, 24), SECONDARY = Color.rgb(255, 76, 68);

    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private SharedPreferences preferences;
    private SecureStore secureStore;
    private FrameLayout content;
    private ArcadeBackdrop arcadeBackdrop;
    private LiquidNavBar navigationBar;
    private final ArrayList<LinearLayout> themedCards = new ArrayList<>();
    private TextView globalStatus, mediaInfo, firmwareInfo, updateInfo, aiResult,
            externalWifiState, externalWifiIp, externalWifiHint, sensorResult,
            screenMonitorState, historyView, activeProtocolView, gifServiceState,
            analysisResultView, offlineStoreState, operationModeState, hardwareUsageState;
    private ProgressBar globalProgress;
    private EditText deviceUrlInput, wifiSsid, wifiPassword, mqttUri, mqttUser, mqttPassword,
            mqttTopic, brightnessInput, aiEndpoint, aiModel, aiKey, aiQuestion,
            experimentRateInput, experimentDurationInput, idleTitleInput, idleMessageInput;
    private CheckBox keepRecoveryAp, remoteEnabled;
    private Spinner transportSpinner;
    private ImageView mediaPreview;
    private byte[] selectedFirmware;
    private Bitmap selectedPreview;
    private Bitmap selectedCropSource;
    private Movie selectedMovie;
    private RectF selectedCropRect;
    private String selectedMediaName;
    private byte[] lastGifComparisonFrame;
    private String lastStationIp;
    private volatile boolean gifStreaming;
    private String latestApkUrl, latestFirmwareUrl;
    private String currentProtocol;
    private int currentSection, visualPreset, wallpaperOpacity, panelOpacity,
            hudOpacity, appGlassOpacity, gifSpeedPercent;
    private final Runnable styleSyncRunnable = () -> sendVisualStyle(false);

    private BluetoothAdapter bluetoothAdapter;
    private BluetoothLeScanner bleScanner;
    private BluetoothGatt bluetoothGatt;
    private BluetoothGattCharacteristic commandCharacteristic, statusCharacteristic,
            otaControlCharacteristic, otaDataCharacteristic, fileControlCharacteristic,
            fileDataCharacteristic, experimentDataCharacteristic;
    private boolean bleReady, scanAfterPermission, blePendingQuiet, screenMonitorActive;
    private String blePendingCommand = "";
    private int bleMtu = 23, bleTransferOffset, blePendingLength;
    private byte[] bleTransferData;
    private String bleTransferPhase = "idle", bleTransferKind = "";
    private Runnable bleTransferCompletion;
    private File offlineSyncFile;
    private OutputStream offlineSyncOutput;
    private OutputStream liveCaptureOutput;
    private long offlineSyncBytes, lastLiveElapsed = -1;
    private int liveCaptureSamples;
    private final Runnable liveCaptureIdleCloseRunnable = this::finishLiveCaptureAfterIdle;
    private final Runnable screenMonitorRunnable = new Runnable() {
        @Override public void run() {
            if (!screenMonitorActive || currentSection != 4) return;
            requestDeviceStatus(true);
            mainHandler.postDelayed(this, 1000);
        }
    };

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        preferences = getSharedPreferences("labcapsule", MODE_PRIVATE);
        secureStore = new SecureStore();
        visualPreset = preferences.getInt("visual_preset", 0);
        wallpaperOpacity = preferences.getInt("wallpaper_opacity", 82);
        panelOpacity = preferences.getInt("panel_opacity", 76);
        hudOpacity = preferences.getInt("hud_opacity", 100);
        appGlassOpacity = preferences.getInt("app_glass_opacity", 86);
        gifSpeedPercent = Math.max(25, Math.min(300,
                preferences.getInt("gif_speed_percent", 100)));
        applyThemePalette(visualPreset);
        Window window = getWindow();
        window.setStatusBarColor(Color.TRANSPARENT);
        window.setNavigationBarColor(Color.TRANSPARENT);
        window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        if (Build.VERSION.SDK_INT >= 23) window.getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN);
        BluetoothManager manager = (BluetoothManager) getSystemService(BLUETOOTH_SERVICE);
        bluetoothAdapter = manager == null ? null : manager.getAdapter();
        buildShell();
        showSection(0);
        if (preferences.getBoolean("auto_update", true)) checkForUpdates(true);
    }

    private void buildShell() {
        FrameLayout root = new FrameLayout(this);
        arcadeBackdrop = new ArcadeBackdrop(this);
        root.addView(arcadeBackdrop, new FrameLayout.LayoutParams(-1, -1));
        content = new FrameLayout(this);
        FrameLayout.LayoutParams cp = new FrameLayout.LayoutParams(-1, -1);
        cp.bottomMargin = dp(102);
        root.addView(content, cp);
        navigationBar = new LiquidNavBar(this);
        navigationBar.setItems(new String[]{"首页", "实验", "数据", "AI", "设置"});
        navigationBar.listener = this::showSection;
        FrameLayout.LayoutParams np = new FrameLayout.LayoutParams(-1, dp(82), Gravity.BOTTOM);
        np.setMargins(dp(14), 0, dp(14), dp(14));
        root.addView(navigationBar, np);
        setContentView(root);
    }

    private void showSection(int index) {
        if (index != 4) stopScreenMonitorSilently();
        currentSection = index;
        themedCards.clear();
        View page = index == 0 ? buildHomePage() : index == 1 ? buildExperimentPage()
                : index == 2 ? buildDataPage() : index == 3 ? buildAiPage()
                : buildSettingsPage();
        page.setAlpha(0f);
        page.setTranslationY(dp(18));
        content.removeAllViews();
        content.addView(page, new FrameLayout.LayoutParams(-1, -1));
        page.animate().alpha(1).translationY(0).setDuration(280).start();
    }

    private void applyThemePalette(int preset) {
        visualPreset = Math.max(0, Math.min(2, preset));
        if (visualPreset == 1) {
            CANVAS = Color.rgb(22, 10, 13); PANEL = Color.rgb(31, 20, 21);
            BLUE = Color.rgb(255, 76, 68); SECONDARY = Color.rgb(246, 216, 14);
            INK = Color.rgb(248, 242, 222); MUTED = Color.rgb(176, 157, 151);
        } else if (visualPreset == 2) {
            CANVAS = Color.rgb(5, 18, 24); PANEL = Color.rgb(8, 30, 37);
            BLUE = Color.rgb(40, 224, 230); SECONDARY = Color.rgb(190, 241, 57);
            INK = Color.rgb(235, 250, 244); MUTED = Color.rgb(126, 174, 179);
        } else {
            CANVAS = Color.rgb(14, 14, 15); PANEL = Color.rgb(25, 25, 24);
            BLUE = Color.rgb(246, 216, 14); SECONDARY = Color.rgb(255, 76, 68);
            INK = Color.rgb(247, 243, 224); MUTED = Color.rgb(169, 166, 151);
        }
    }

    private void refreshThemeSurfaces() {
        for (LinearLayout card : themedCards) card.setBackground(cardBackground());
        if (arcadeBackdrop != null) arcadeBackdrop.invalidate();
        if (navigationBar != null) navigationBar.invalidate();
        if (mediaPreview instanceof WallpaperPreview) {
            ((WallpaperPreview) mediaPreview).setStyle(visualPreset, wallpaperOpacity,
                    panelOpacity, hudOpacity);
        }
    }

    private ScrollView page(String title, String subtitle) {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(18), dp(48), dp(18), dp(28));
        scroll.addView(root);
        TextView eyebrow = label("// FIELD CONSOLE · 03", 11, BLUE, true);
        eyebrow.setLetterSpacing(.12f);
        eyebrow.setPadding(0, 0, 0, dp(5));
        root.addView(eyebrow);
        root.addView(label(title, 31, INK, true));
        TextView sub = label(subtitle, 14, MUTED, false);
        sub.setPadding(0, dp(3), 0, dp(16));
        root.addView(sub);
        globalStatus = label("就绪", 13, MUTED, false);
        globalStatus.setPadding(dp(12), dp(10), dp(12), dp(10));
        globalStatus.setBackground(roundRect(Color.argb(205, Color.red(PANEL),
                Color.green(PANEL), Color.blue(PANEL)), 8,
                Color.argb(150, Color.red(BLUE), Color.green(BLUE), Color.blue(BLUE))));
        root.addView(globalStatus, matchWrap(dp(10)));
        globalProgress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        globalProgress.setMax(100);
        globalProgress.setVisibility(View.GONE);
        root.addView(globalProgress, matchWrap(dp(8)));
        scroll.setTag(root);
        return scroll;
    }

    private LinearLayout pageRoot(ScrollView page) { return (LinearLayout) page.getTag(); }

    private View buildHomePage() {
        ScrollView page = page("实验中枢", "从问题、采集到结果，而不是一组设备设置");
        LinearLayout root = pageRoot(page);
        LinearLayout hero = card(root, new int[]{BLUE, SECONDARY});
        hero.addView(label("LAB / RUN CONSOLE", 12, Color.rgb(18, 18, 18), true));
        hero.addView(label("今天要验证什么？", 25, Color.rgb(18, 18, 18), true));
        TextView connection = label(preferences.getBoolean("sta_connected", false)
                ? "● 设备已在局域网在线 · " + preferences.getString("sta_ip", "")
                : bleReady ? "● BLE 在线，可直接开始实验" : "○ 等待设备连接",
                13, Color.rgb(30, 30, 30), true);
        connection.setPadding(0, dp(8), 0, 0);
        hero.addView(connection);

        LinearLayout mode = card(root, null);
        section(mode, "设备工作模式", "闲置时展示连接通知与硬件负载；实验时实时直传数据");
        operationModeState = label("idle".equals(preferences.getString(
                "operation_mode", "experiment")) ? "● 闲置信息模式" : "● 实验直传模式",
                15, BLUE, true);
        hardwareUsageState = label(preferences.getString("hardware_summary",
                "硬件利用率尚未读取"), 13, MUTED, false);
        hardwareUsageState.setPadding(0, dp(5), 0, dp(6));
        mode.addView(operationModeState);
        mode.addView(hardwareUsageState);
        mode.addView(row(button("闲置信息", false, v -> showIdleModeDialog()),
                button("实验直传", true, v -> setOperationMode("experiment", "", "")),
                button("刷新负载", false, v -> fetchHardwareStatus())));

        LinearLayout quick = card(root, null);
        section(quick, "快速实验", "预设会生成真实 Experiment Protocol 并立即下发");
        quick.addView(button("桌面振动 · 200 Hz / 20 s", true,
                v -> startPresetExperiment("桌面振动记录", 200, 20)), matchWrap(0));
        quick.addView(row(button("碰撞冲击 · 500 Hz", false,
                        v -> startPresetExperiment("碰撞冲击响应", 500, 8)),
                button("姿态变化 · 100 Hz", false,
                        v -> startPresetExperiment("姿态变化轨迹", 100, 30))), matchWrap(dp(7)));
        quick.addView(row(button("设计实验", false, v -> navigateSection(1)),
                button("AI 生成协议", false, v -> navigateSection(3)),
                button("查看记录", false, v -> navigateSection(2))), matchWrap(dp(7)));

        LinearLayout now = card(root, null);
        section(now, "当前任务", "后台任务不会因离开页面而消失");
        String protocol = preferences.getString("last_protocol_name", "尚未开始实验");
        now.addView(label("实验：" + protocol + "\n最近样本数：" +
                preferences.getLong("last_sample_count", 0), 15, INK, true));
        String gifState = preferences.getBoolean("gif_service_running", false)
                ? preferences.getString("gif_service_message", "GIF 后台播放中")
                : "GIF 后台播放器未运行";
        gifServiceState = label(gifState, 13,
                preferences.getBoolean("gif_service_running", false) ? GREEN : MUTED, false);
        gifServiceState.setPadding(0, dp(8), 0, 0);
        now.addView(gifServiceState);
        now.addView(row(button("刷新设备", true, v -> fetchStatus()),
                button("停止实验", false, v -> sendAction("stop")),
                button("中止全部", false, v -> sendAction("abort"))), matchWrap(dp(7)));
        return page;
    }

    private View buildDevicePage() {
        ScrollView page = page("LabCapsule", "一个可扩展、可联网的实验实体小组件");
        LinearLayout root = pageRoot(page);
        LinearLayout hero = card(root, new int[]{BLUE, SECONDARY});
        hero.addView(label("●  FIELD LINK / 等待连接", 22, Color.rgb(16, 16, 16), true));
        TextView hint = label("局域网、远程 MQTT 与 BLE 三种通道可并行使用", 13,
                Color.argb(220, 16, 16, 16), false);
        hint.setPadding(0, dp(7), 0, dp(6));
        hero.addView(hint);
        LinearLayout connection = card(root, null);
        section(connection, "连接中心", "手机无需停留在无互联网的设备热点");
        deviceUrlInput = input(preferences.getString("device_url", "http://192.168.4.1"),
                "设备 IP 或 URL", false);
        connection.addView(deviceUrlInput, matchWrap(0));
        transportSpinner = transportSelector();
        connection.addView(transportSpinner, matchWrap(dp(6)));
        connection.addView(row(button("检测设备", true, v -> fetchStatus()),
                button("扫描 BLE", false, v -> startBleScan())));
        connection.addView(row(button("Wi‑Fi 系统设置", false,
                        v -> startActivity(new Intent(Settings.ACTION_WIFI_SETTINGS))),
                button("读取传感器", false, v -> fetchSensors())));
        connection.addView(row(button("蓝牙一键配网", true, v -> showBleWifiDialog()),
                button("恢复设备热点", false, v -> restoreRecoveryAp())), matchWrap(dp(7)));
        LinearLayout wifiStatus = card(root, null);
        section(wifiStatus, "外部 Wi‑Fi 状态", "这里直接显示连接结果，不需要查找原始 JSON");
        externalWifiState = label("● 尚未读取设备状态", 17, MUTED, true);
        externalWifiIp = label("局域网 IP：尚未获取", 15, INK, false);
        externalWifiHint = label("只需 BLE 连接即可配置路由器，无需让手机断网", 13, MUTED, false);
        externalWifiState.setPadding(0, 0, 0, dp(5));
        externalWifiIp.setTextIsSelectable(true);
        externalWifiHint.setPadding(0, dp(5), 0, dp(7));
        wifiStatus.addView(externalWifiState);
        wifiStatus.addView(externalWifiIp);
        wifiStatus.addView(externalWifiHint);
        wifiStatus.addView(row(button("刷新 Wi‑Fi 状态", true, v -> fetchStatus()),
                button("使用此局域网 IP", false, v -> useStationIp())));
        wifiStatus.addView(button("打开 GitHub 配网说明", false,
                v -> openUrl(WIFI_GUIDE_URL)), matchWrap(dp(7)));
        renderExternalWifi(preferences.getBoolean("sta_configured", false),
                preferences.getBoolean("sta_connected", false),
                preferences.getString("sta_ip", "0.0.0.0"),
                preferences.getString("recovery_ap", "LabCapsule"));
        mainHandler.postDelayed(this::fetchStatus, 350);
        LinearLayout quick = card(root, null);
        section(quick, "快捷控制", "常用状态一触即达");
        quick.addView(row(button("主页", true, v -> sendAction("home")),
                button("开始实验", false, v -> sendAction("ok")),
                button("中止", false, v -> sendAction("back"))));
        return page;
    }

    private View buildScreenPage() {
        ScrollView page = page("屏幕与壁纸", "壁纸是所有设备页面的底层，HUD 始终叠加显示");
        LinearLayout root = pageRoot(page);
        LinearLayout media = card(root, null);
        section(media, "壁纸工作台", "先裁剪，再预览壁纸与设备界面的最终合成效果");
        mediaPreview = new WallpaperPreview(this);
        mediaPreview.setScaleType(ImageView.ScaleType.CENTER_CROP);
        ((WallpaperPreview) mediaPreview).setStyle(visualPreset, wallpaperOpacity,
                panelOpacity, hudOpacity);
        mediaPreview.setBackground(roundRect(CANVAS, 10, BLUE));
        media.addView(mediaPreview, new LinearLayout.LayoutParams(-1, -2));
        mediaInfo = label("选择媒体后确认 3:4 裁剪；预览中的字卡不会写入壁纸文件", 13,
                MUTED, false);
        mediaInfo.setPadding(0, dp(9), 0, dp(4));
        media.addView(mediaInfo);
        transportSpinner = transportSelector();
        media.addView(transportSpinner, matchWrap(dp(4)));
        addGifSpeedSlider(media);
        media.addView(row(button("选择并裁剪", false, v -> chooseMedia()),
                button("重新裁剪", false, v -> reopenCropEditor()),
                button("设为设备壁纸", true, v -> saveWallpaper())));
        media.addView(row(button("临时单帧", false, v -> sendSelectedFrame()),
                button("播放 GIF", true, v -> startGifStream()),
                button("停止播放", false, v -> stopGifStream())));

        LinearLayout monitor = card(root, null);
        section(monitor, "实时屏幕镜像", "严格 240×320 比例；每秒同步设备页面、状态与 HUD");
        screenMonitorState = label(screenMonitorActive
                ? "● 正在同步设备渲染状态" : "● 尚未开始监看", 13,
                screenMonitorActive ? GREEN : MUTED, true);
        screenMonitorState.setPadding(0, 0, 0, dp(7));
        monitor.addView(screenMonitorState);
        monitor.addView(label("ST7789 是只写屏，本功能镜像设备实际渲染状态与本机壁纸，"
                + "不会伪装成面板像素回读。", 12, MUTED, false));
        monitor.addView(row(button("开始实时监看", true, v -> startScreenMonitor()),
                button("停止", false, v -> stopScreenMonitor())), matchWrap(dp(7)));
        if (screenMonitorActive) mainHandler.post(screenMonitorRunnable);

        LinearLayout appearance = card(root, null);
        section(appearance, "界面混合台", "所有滑杆均为 0–100 连续调节，预览立即更新");
        Spinner preset = spinner(new String[]{"街机黄黑", "信号红灰", "冷蓝录像"});
        preset.setSelection(visualPreset);
        preset.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view,
                                                  int position, long id) {
                if (position == visualPreset) return;
                applyThemePalette(position);
                preferences.edit().putInt("visual_preset", visualPreset).apply();
                scheduleVisualStyleSync();
                mainHandler.post(() -> showSection(currentSection));
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });
        appearance.addView(preset, matchWrap(0));
        addOpacitySlider(appearance, "壁纸可见度", wallpaperOpacity, value -> {
            wallpaperOpacity = value;
            preferences.edit().putInt("wallpaper_opacity", value).apply();
            refreshThemeSurfaces(); scheduleVisualStyleSync();
        });
        addOpacitySlider(appearance, "设备面板遮罩", panelOpacity, value -> {
            panelOpacity = value;
            preferences.edit().putInt("panel_opacity", value).apply();
            refreshThemeSurfaces(); scheduleVisualStyleSync();
        });
        addOpacitySlider(appearance, "设备 HUD / 文字", hudOpacity, value -> {
            hudOpacity = value;
            preferences.edit().putInt("hud_opacity", value).apply();
            refreshThemeSurfaces(); scheduleVisualStyleSync();
        });
        addOpacitySlider(appearance, "APK 面板 / 导航玻璃", appGlassOpacity, value -> {
            appGlassOpacity = value;
            preferences.edit().putInt("app_glass_opacity", value).apply();
            refreshThemeSurfaces();
        });
        appearance.addView(button("立即同步到设备", true,
                v -> sendVisualStyle(true)), matchWrap(dp(8)));

        LinearLayout remote = card(root, null);
        section(remote, "屏幕遥控", "壁纸留在底层；双缓冲切换不会先清黑屏");
        remote.addView(row(button("主页", false, v -> sendAction("home")),
                button("设置", false, v -> sendAction("settings")),
                button("开发诊断", false, v -> sendAction("developer"))));
        remote.addView(row(button("彩条", false, v -> sendAction("test")),
                button("壁纸主页", false, v -> sendAction("wallpaper")),
                button("颜色反转", false, v -> sendAction("invert"))));
        remote.addView(row(button("背光开", true, v -> sendAction("bl_on")),
                button("背光关", false, v -> sendAction("bl_off"))));
        remote.addView(center(button("↑", false, v -> sendAction("up"))));
        remote.addView(row(button("←", false, v -> sendAction("left")),
                button("OK", true, v -> sendAction("ok")),
                button("→", false, v -> sendAction("right"))));
        remote.addView(center(button("↓", false, v -> sendAction("down"))));
        return page;
    }

    private View buildExperimentPage() {
        ScrollView page = page("实验设计", "选择参数、确认传感器并运行可复现实验");
        LinearLayout root = pageRoot(page);
        LinearLayout runner = card(root, new int[]{BLUE, SECONDARY});
        section(runner, "自定义采集", "采样率 10–500 Hz，时长 1–3600 秒");
        experimentRateInput = input("200", "采样率 Hz", false);
        experimentDurationInput = input("20", "时长 秒", false);
        runner.addView(row(experimentRateInput, experimentDurationInput));
        runner.addView(row(button("开始采集", true, v -> startCustomExperiment()),
                button("停止", false, v -> sendAction("stop")),
                button("中止", false, v -> sendAction("abort"))), matchWrap(dp(7)));
        runner.addView(label("实验模式会把数据直接发送到已连接的手机、电脑或 MQTT；"
                + "无人接收的样本自动进入设备离线缓存。", 12,
                Color.rgb(36, 36, 36), false), matchWrap(dp(6)));
        runner.addView(button("切换为实验直传模式", false,
                v -> setOperationMode("experiment", "", "")), matchWrap(dp(5)));
        activeProtocolView = label(preferences.getString("last_protocol_json",
                "尚未下发实验协议"), 12, Color.rgb(28, 28, 28), false);
        activeProtocolView.setTextIsSelectable(true);
        activeProtocolView.setPadding(0, dp(8), 0, 0);
        runner.addView(activeProtocolView);
        LinearLayout sensors = card(root, null);
        section(sensors, "传感器扩展", "运动、环境、电气、测距与模拟量驱动注册表");
        sensors.addView(label("GPIO8 / GPIO9 是扩展 I²C 总线。固件可发现 MPU6050、BME280、SHT3x、INA219、ADS1115、VL53L0X，并继续注册 SPI、UART、ADC、OneWire 驱动。", 14, INK, false));
        sensors.addView(row(button("扫描传感器", true, v -> fetchSensors()),
                button("刷新状态", false, v -> fetchStatus())));
        sensorResult = label("尚未扫描。BLE 连接时也可直接扫描 I²C。", 13, MUTED, false);
        sensorResult.setTextIsSelectable(true);
        sensorResult.setPadding(0, dp(8), 0, 0);
        sensors.addView(sensorResult);
        return page;
    }

    private View buildDataPage() {
        ScrollView page = page("实验记录", "本机保存实验协议和运行时间，可直接分享");
        LinearLayout root = pageRoot(page);
        LinearLayout summary = card(root, null);
        section(summary, "记录库", "每次从首页、实验页或 AI 页启动都会自动登记");
        historyView = label(buildHistoryText(), 13, INK, false);
        historyView.setTextIsSelectable(true);
        summary.addView(historyView);
        summary.addView(row(button("分享 CSV 摘要", true, v -> shareHistory()),
                button("清空记录", false, v -> clearHistory())), matchWrap(dp(8)));
        LinearLayout deviceCache = card(root, null);
        section(deviceCache, "设备离线缓存",
                "无 BLE/MQTT 接收端时设备自动落盘；连接后同步到手机");
        offlineStoreState = label("尚未读取设备缓存。仅有 5 GHz Wi‑Fi 时可直接使用 BLE。",
                13, MUTED, false);
        offlineStoreState.setTextIsSelectable(true);
        deviceCache.addView(offlineStoreState);
        deviceCache.addView(row(button("读取状态", false, v -> refreshOfflineStore()),
                button("同步并分析", true, v -> syncOfflineData()),
                button("清空设备缓存", false, v -> confirmClearOfflineData())),
                matchWrap(dp(7)));
        LinearLayout analysis = card(root, null);
        section(analysis, "六轴 CSV 分析", "在手机端计算 RMS、绝对峰值、FFT 主频");
        analysisResultView = label(preferences.getString("last_analysis",
                "尚未导入 CSV。支持 timestamp_us + AX/AY/AZ/GX/GY/GZ。"),
                13, MUTED, false);
        analysisResultView.setTextIsSelectable(true);
        analysis.addView(analysisResultView);
        analysis.addView(row(button("导入 CSV 并分析", true, v -> chooseCsv()),
                button("分享分析", false, v -> shareAnalysis())), matchWrap(dp(7)));
        analysis.addView(row(button("开始新实验", false, v -> navigateSection(1)),
                button("AI 设计", false, v -> navigateSection(3))), matchWrap(dp(7)));
        return page;
    }

    private void navigateSection(int index) {
        if (navigationBar != null) navigationBar.select(index);
        showSection(index);
    }

    private void startPresetExperiment(String name, int rate, int duration) {
        try {
            currentProtocol = new JSONObject().put("name", name)
                    .put("sample_rate_hz", rate).put("duration_seconds", duration)
                    .put("groups", new JSONArray().put("当前实验组"))
                    .put("analysis", new JSONArray().put("RMS").put("Peak").put("FFT"))
                    .put("source", "apk_preset").toString(2);
            executeProtocol(currentProtocol);
        } catch (Exception error) { status("预设无法启动：" + error.getMessage(), false); }
    }

    private void startCustomExperiment() {
        try {
            int rate = Integer.parseInt(experimentRateInput.getText().toString().trim());
            int duration = Integer.parseInt(experimentDurationInput.getText().toString().trim());
            if (rate < 10 || rate > 500 || duration < 1 || duration > 3600) {
                status("采样率需为 10–500 Hz，时长需为 1–3600 秒", false); return;
            }
            currentProtocol = new JSONObject().put("name", "自定义运动实验")
                    .put("sample_rate_hz", rate).put("duration_seconds", duration)
                    .put("groups", new JSONArray().put("当前实验组"))
                    .put("analysis", new JSONArray().put("RMS").put("Peak").put("FFT"))
                    .put("source", "apk_custom").toString(2);
            executeProtocol(currentProtocol);
        } catch (Exception error) { status("实验参数无效：" + error.getMessage(), false); }
    }

    private void executeProtocol(String protocolText) {
        try {
            JSONObject protocol = new JSONObject(protocolText);
            int rate = protocol.getInt("sample_rate_hz");
            int duration = protocol.getInt("duration_seconds");
            String name = protocol.optString("name", "未命名实验");
            if (rate < 10 || rate > 500 || duration < 1 || duration > 3600)
                throw new Exception("协议采样率或时长超出安全范围");
            recordExperiment(protocol);
            preferences.edit().putString("last_protocol_name", name)
                    .putString("last_protocol_json", protocol.toString(2))
                    .putString("operation_mode", "experiment").apply();
            if (activeProtocolView != null) activeProtocolView.setText(protocol.toString(2));
            status("正在下发实验协议：" + name, true);
            if (selectedTransport() == 1) {
                writeBleCommand("START:" + rate + ":" + duration);
            } else {
                http("POST", "/api/experiment?rate=" + rate + "&duration=" + duration,
                        new byte[0], "application/octet-stream",
                        result -> status("实验已启动：" + name, true));
            }
        } catch (Exception error) { status("协议无法执行：" + error.getMessage(), false); }
    }

    private void recordExperiment(JSONObject protocol) {
        try {
            JSONArray history = new JSONArray(preferences.getString("experiment_history", "[]"));
            JSONArray updated = new JSONArray();
            updated.put(new JSONObject().put("startedAt", System.currentTimeMillis())
                    .put("name", protocol.optString("name", "未命名实验"))
                    .put("rate", protocol.optInt("sample_rate_hz"))
                    .put("duration", protocol.optInt("duration_seconds"))
                    .put("transport", selectedTransport() == 1 ? "BLE" : "Wi-Fi"));
            for (int index = 0; index < history.length() && index < 49; ++index)
                updated.put(history.getJSONObject(index));
            preferences.edit().putString("experiment_history", updated.toString()).apply();
        } catch (Exception ignored) { }
    }

    private String buildHistoryText() {
        try {
            JSONArray history = new JSONArray(preferences.getString("experiment_history", "[]"));
            if (history.length() == 0) return "尚无实验记录。";
            StringBuilder output = new StringBuilder();
            java.text.SimpleDateFormat format = new java.text.SimpleDateFormat(
                    "MM-dd HH:mm", Locale.getDefault());
            for (int index = 0; index < history.length(); ++index) {
                JSONObject item = history.getJSONObject(index);
                if (index > 0) output.append("\n\n");
                output.append(index + 1).append(". ").append(item.optString("name"))
                        .append("\n   ").append(format.format(new java.util.Date(
                                item.optLong("startedAt"))))
                        .append(" · ").append(item.optInt("rate")).append(" Hz · ")
                        .append(item.optInt("duration")).append(" s · ")
                        .append(item.optString("transport"));
            }
            return output.toString();
        } catch (Exception error) { return "记录读取失败：" + error.getMessage(); }
    }

    private void shareHistory() {
        try {
            JSONArray history = new JSONArray(preferences.getString("experiment_history", "[]"));
            StringBuilder csv = new StringBuilder("started_at,name,sample_rate_hz,duration_seconds,transport\n");
            for (int index = 0; index < history.length(); ++index) {
                JSONObject item = history.getJSONObject(index);
                csv.append(item.optLong("startedAt")).append(',').append('"')
                        .append(item.optString("name").replace("\"", "\"\""))
                        .append("\",").append(item.optInt("rate")).append(',')
                        .append(item.optInt("duration")).append(',')
                        .append(item.optString("transport")).append('\n');
            }
            Intent share = new Intent(Intent.ACTION_SEND).setType("text/csv")
                    .putExtra(Intent.EXTRA_SUBJECT, "LabCapsule 实验记录")
                    .putExtra(Intent.EXTRA_TEXT, csv.toString());
            startActivity(Intent.createChooser(share, "分享实验记录"));
        } catch (Exception error) { status("记录分享失败：" + error.getMessage(), false); }
    }

    private void clearHistory() {
        new AlertDialog.Builder(this).setTitle("清空实验记录？")
                .setMessage("只会删除 APK 中的实验元数据，不会删除 PC 上的 CSV。")
                .setNegativeButton("取消", null)
                .setPositiveButton("清空", (dialog, which) -> {
                    preferences.edit().remove("experiment_history").apply();
                    if (historyView != null) historyView.setText("尚无实验记录。");
                    status("实验记录已清空", true);
                }).show();
    }

    private View buildAiPage() {
        ScrollView page = page("AI 实验助手", "使用你自己的 OpenAI 兼容 API 生成实验协议");
        LinearLayout root = pageRoot(page);
        LinearLayout provider = card(root, null);
        section(provider, "模型服务", "API 密钥由 Android Keystore 加密，不下发设备");
        aiEndpoint = input(preferences.getString("ai_endpoint",
                "https://api.deepseek.com/chat/completions"), "API Endpoint", false);
        aiModel = input(preferences.getString("ai_model", "deepseek-chat"), "模型名称", false);
        aiKey = input(secureStore.get("ai_key"), "API Key", true);
        provider.addView(aiEndpoint, matchWrap(0));
        provider.addView(aiModel, matchWrap(dp(5)));
        provider.addView(aiKey, matchWrap(dp(5)));
        provider.addView(button("保存 AI 设置", false, v -> saveAiSettings()), matchWrap(dp(6)));
        LinearLayout prompt = card(root, null);
        section(prompt, "实验问题", "例如：比较不同桌面材料上的振动衰减");
        aiQuestion = input("", "输入自然语言问题", false);
        aiQuestion.setMinLines(3);
        aiQuestion.setSingleLine(false);
        prompt.addView(aiQuestion, matchWrap(0));
        prompt.addView(row(button("生成协议", true, v -> generateProtocol()),
                button("发送并开始实验", false, v -> sendCurrentProtocol())), matchWrap(dp(8)));
        aiResult = label("生成结果将在这里显示。", 13, MUTED, false);
        aiResult.setTextIsSelectable(true);
        aiResult.setPadding(0, dp(12), 0, 0);
        prompt.addView(aiResult);
        return page;
    }

    private View buildSettingsPage() {
        ScrollView page = page("设置", "网络、远程连接、更新与本地偏好");
        LinearLayout root = pageRoot(page);
        addDeviceSettingsGroup(root);
        addDisplaySettingsGroup(root);
        addFirmwareSettingsGroup(root);
        LinearLayout network = card(root, null);
        section(network, "外部 Wi‑Fi", "推荐连接 BLE 后直接保存；手机全程保持正常联网");
        TextView wifiBandNotice = label(
                "硬件限制：ESP32‑S3 只能连接 2.4 GHz Wi‑Fi，不能连接纯 5 GHz。"
                        + "没有 2.4 GHz 路由器时，可继续使用 BLE，或临时开启手机的 2.4 GHz 兼容热点。",
                13, RED, true);
        network.addView(wifiBandNotice, matchWrap(dp(4)));
        transportSpinner = transportSelector();
        network.addView(transportSpinner, matchWrap(0));
        wifiSsid = input(preferences.getString("wifi_ssid", ""), "路由器 SSID", false);
        wifiPassword = input(secureStore.get("wifi_password"), "路由器密码", true);
        network.addView(wifiSsid, matchWrap(0));
        network.addView(wifiPassword, matchWrap(dp(5)));
        keepRecoveryAp = check("保留 LabCapsule 恢复热点（推荐）", true);
        keepRecoveryAp.setEnabled(false);
        network.addView(keepRecoveryAp);
        section(network, "远程 MQTT", "设备主动连接服务器，无需开放路由器入站端口");
        mqttUri = input(preferences.getString("mqtt_uri", ""), "mqtts://broker.example.com:8883", false);
        mqttUser = input(preferences.getString("mqtt_user", ""), "MQTT 用户名", false);
        mqttPassword = input(secureStore.get("mqtt_password"), "MQTT 密码", true);
        mqttTopic = input(preferences.getString("mqtt_topic", "labcapsule"), "主题前缀", false);
        remoteEnabled = check("启用远程连接", preferences.getBoolean("remote", false));
        network.addView(mqttUri, matchWrap(dp(5)));
        network.addView(mqttUser, matchWrap(dp(5)));
        network.addView(mqttPassword, matchWrap(dp(5)));
        network.addView(mqttTopic, matchWrap(dp(5)));
        network.addView(remoteEnabled);
        brightnessInput = input(preferences.getString("brightness", "90"),
                "屏幕亮度 0–100", false);
        network.addView(brightnessInput, matchWrap(dp(5)));
        network.addView(button("保存并连接", true, v -> saveNetworkSettings()), matchWrap(dp(8)));
        network.addView(button("查看普通用户配网步骤", false,
                v -> openUrl(WIFI_GUIDE_URL)), matchWrap(dp(6)));
        LinearLayout updates = card(root, null);
        section(updates, "自动更新", "通过 GitHub Releases 查找 APK 和固件");
        CheckBox automatic = check("启动时自动检查更新", preferences.getBoolean("auto_update", true));
        automatic.setOnCheckedChangeListener((button, checked) ->
                preferences.edit().putBoolean("auto_update", checked).apply());
        updates.addView(automatic);
        updateInfo = label("当前 APK：" + APP_VERSION, 13, MUTED, false);
        updateInfo.setPadding(0, dp(5), 0, dp(5));
        updates.addView(updateInfo);
        updates.addView(row(button("检查更新", false, v -> checkForUpdates(false)),
                button("下载新版 APK", true, v -> downloadLatestApk())));
        LinearLayout about = card(root, null);
        section(about, "关于", "LabCapsule V0.6.0 · Connected Experiment Companion");
        about.addView(label("默认语言：简体中文\n协议：HTTP + MQTT + BLE GATT\n屏幕：240×320 RGB565 双缓冲\n仓库：github.com/" + REPOSITORY, 13, MUTED, false));
        about.addView(button("查看 V0.6 工作模式、通知与 GIF 指南", false,
                v -> openUrl(V060_GUIDE_URL)), matchWrap(dp(7)));
        return page;
    }

    private LinearLayout collapsedGroup(LinearLayout root, String title, String subtitle) {
        LinearLayout shell = card(root, null);
        TextView header = label("＋  " + title, 18, INK, true);
        header.setPadding(0, dp(2), 0, dp(4));
        TextView hint = label(subtitle, 12, MUTED, false);
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setVisibility(View.GONE);
        shell.addView(header);
        shell.addView(hint);
        shell.addView(body, matchWrap(dp(8)));
        header.setOnClickListener(v -> {
            boolean opening = body.getVisibility() != View.VISIBLE;
            body.setVisibility(opening ? View.VISIBLE : View.GONE);
            header.setText((opening ? "－  " : "＋  ") + title);
            if (opening) {
                body.setAlpha(0f);
                body.animate().alpha(1f).setDuration(180).start();
            }
        });
        hint.setOnClickListener(v -> header.performClick());
        return body;
    }

    private void addDeviceSettingsGroup(LinearLayout root) {
        LinearLayout body = collapsedGroup(root, "设备与连接",
                "BLE、局域网地址、恢复热点和设备遥控（默认折叠）");
        deviceUrlInput = input(preferences.getString("device_url", "http://192.168.4.1"),
                "设备 IP 或 URL", false);
        body.addView(deviceUrlInput, matchWrap(0));
        transportSpinner = transportSelector();
        body.addView(transportSpinner, matchWrap(dp(6)));
        body.addView(row(button("检测设备", true, v -> fetchStatus()),
                button("扫描 BLE", false, v -> startBleScan())), matchWrap(dp(6)));
        body.addView(row(button("蓝牙一键配网", true, v -> showBleWifiDialog()),
                button("恢复设备热点", false, v -> restoreRecoveryAp())), matchWrap(dp(6)));
        externalWifiState = label("● 尚未读取设备状态", 16, MUTED, true);
        externalWifiIp = label("局域网 IP：尚未获取", 14, INK, false);
        externalWifiHint = label("展开后点击检测设备，或只用 BLE 配网", 12, MUTED, false);
        body.addView(externalWifiState, matchWrap(dp(8)));
        body.addView(externalWifiIp);
        body.addView(externalWifiHint);
        body.addView(row(button("使用局域网 IP", false, v -> useStationIp()),
                button("扫描 I²C", false, v -> fetchSensors())), matchWrap(dp(6)));
        body.addView(row(button("主页", false, v -> sendAction("home")),
                button("设置页", false, v -> sendAction("settings")),
                button("开发诊断", false, v -> sendAction("developer"))), matchWrap(dp(6)));
        section(body, "闲置 / 实验模式", "手机或电脑连接后可让屏幕持续发挥作用");
        operationModeState = label("● 等待读取设备工作模式", 14, MUTED, true);
        hardwareUsageState = label(preferences.getString("hardware_summary",
                "硬件利用率尚未读取"), 12, MUTED, false);
        body.addView(operationModeState, matchWrap(dp(4)));
        body.addView(hardwareUsageState, matchWrap(dp(4)));
        body.addView(row(button("进入闲置面板", false, v -> showIdleModeDialog()),
                button("进入实验直传", true,
                        v -> setOperationMode("experiment", "", ""))), matchWrap(dp(5)));
        body.addView(button("刷新硬件使用情况", false,
                v -> fetchHardwareStatus()), matchWrap(dp(5)));
        CheckBox notificationRelay = check("闲置时镜像手机系统通知",
                preferences.getBoolean("notification_relay_enabled", false));
        notificationRelay.setOnCheckedChangeListener((button, checked) -> {
            preferences.edit().putBoolean("notification_relay_enabled", checked).apply();
            if (checked && !notificationRelayGranted()) openNotificationAccess();
        });
        CheckBox notificationPrivacy = check("通知隐私模式（只显示应用名）",
                preferences.getBoolean("notification_relay_private", false));
        notificationPrivacy.setOnCheckedChangeListener((button, checked) ->
                preferences.edit().putBoolean("notification_relay_private", checked).apply());
        body.addView(notificationRelay, matchWrap(dp(7)));
        body.addView(notificationPrivacy);
        body.addView(button("打开 Android 通知访问授权", false,
                v -> openNotificationAccess()), matchWrap(dp(5)));
        renderExternalWifi(preferences.getBoolean("sta_configured", false),
                preferences.getBoolean("sta_connected", false),
                preferences.getString("sta_ip", "0.0.0.0"),
                preferences.getString("recovery_ap", "LabCapsule"));
    }

    private void addDisplaySettingsGroup(LinearLayout root) {
        LinearLayout body = collapsedGroup(root, "屏幕、壁纸与 GIF",
                "媒体、实时镜像、透明度和屏幕遥控（默认折叠）");
        mediaPreview = new WallpaperPreview(this);
        mediaPreview.setScaleType(ImageView.ScaleType.CENTER_CROP);
        ((WallpaperPreview) mediaPreview).setStyle(visualPreset, wallpaperOpacity,
                panelOpacity, hudOpacity);
        mediaPreview.setBackground(roundRect(CANVAS, 10, BLUE));
        body.addView(mediaPreview, new LinearLayout.LayoutParams(-1, -2));
        mediaInfo = label(preferences.getBoolean("gif_service_running", false)
                ? preferences.getString("gif_service_message", "GIF 后台播放中")
                : "选择图片或 GIF，确认 240×320 裁剪后再发送", 13, MUTED, false);
        mediaInfo.setPadding(0, dp(8), 0, dp(5));
        body.addView(mediaInfo);
        transportSpinner = transportSelector();
        body.addView(transportSpinner, matchWrap(dp(4)));
        addGifSpeedSlider(body);
        body.addView(row(button("选择并裁剪", false, v -> chooseMedia()),
                button("重新裁剪", false, v -> reopenCropEditor()),
                button("保存壁纸", true, v -> saveWallpaper())), matchWrap(dp(6)));
        body.addView(row(button("临时单帧", false, v -> sendSelectedFrame()),
                button("后台播放 GIF", true, v -> startGifStream()),
                button("停止 GIF", false, v -> stopGifStream())), matchWrap(dp(6)));

        screenMonitorState = label(screenMonitorActive ? "● 实时同步中" : "● 屏幕镜像未启动",
                13, screenMonitorActive ? GREEN : MUTED, true);
        body.addView(screenMonitorState, matchWrap(dp(9)));
        body.addView(row(button("开始实时镜像", false, v -> startScreenMonitor()),
                button("停止镜像", false, v -> stopScreenMonitor())), matchWrap(dp(5)));

        Spinner preset = spinner(new String[]{"街机黄黑", "信号红灰", "冷蓝录像"});
        preset.setSelection(visualPreset);
        preset.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view,
                                                  int position, long id) {
                if (position == visualPreset) return;
                applyThemePalette(position);
                preferences.edit().putInt("visual_preset", visualPreset).apply();
                scheduleVisualStyleSync();
                mainHandler.post(() -> showSection(4));
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });
        body.addView(preset, matchWrap(dp(9)));
        addOpacitySlider(body, "壁纸可见度", wallpaperOpacity, value -> {
            wallpaperOpacity = value;
            preferences.edit().putInt("wallpaper_opacity", value).apply();
            refreshThemeSurfaces(); scheduleVisualStyleSync();
        });
        addOpacitySlider(body, "设备面板遮罩", panelOpacity, value -> {
            panelOpacity = value;
            preferences.edit().putInt("panel_opacity", value).apply();
            refreshThemeSurfaces(); scheduleVisualStyleSync();
        });
        addOpacitySlider(body, "设备 HUD / 文字", hudOpacity, value -> {
            hudOpacity = value;
            preferences.edit().putInt("hud_opacity", value).apply();
            refreshThemeSurfaces(); scheduleVisualStyleSync();
        });
        addOpacitySlider(body, "APK 面板 / 导航玻璃", appGlassOpacity, value -> {
            appGlassOpacity = value;
            preferences.edit().putInt("app_glass_opacity", value).apply();
            refreshThemeSurfaces();
        });
        body.addView(row(button("同步外观", true, v -> sendVisualStyle(true)),
                button("彩条", false, v -> sendAction("test")),
                button("反色", false, v -> sendAction("invert"))), matchWrap(dp(7)));
        body.addView(row(button("↑", false, v -> sendAction("up")),
                button("←", false, v -> sendAction("left")),
                button("OK", true, v -> sendAction("ok")),
                button("→", false, v -> sendAction("right")),
                button("↓", false, v -> sendAction("down"))), matchWrap(dp(6)));
    }

    private void addFirmwareSettingsGroup(LinearLayout root) {
        LinearLayout body = collapsedGroup(root, "固件与维护",
                "OTA、在线版本和诊断工具（默认折叠）");
        transportSpinner = transportSelector();
        body.addView(transportSpinner, matchWrap(0));
        firmwareInfo = label("尚未选择 .bin 固件", 13, MUTED, false);
        body.addView(firmwareInfo, matchWrap(dp(6)));
        body.addView(row(button("选择固件", false, v -> chooseFirmware()),
                button("开始 OTA", true, v -> startFirmwareUpdate())), matchWrap(dp(6)));
        body.addView(row(button("查找新版", false, v -> checkForUpdates(false)),
                button("下载固件", false, v -> downloadLatestFirmware())), matchWrap(dp(6)));
    }

    private void addOpacitySlider(LinearLayout parent, String title, int initial,
                                  IntValueListener listener) {
        TextView valueLabel = label(title + "  " + initial + "%", 13, INK, true);
        valueLabel.setPadding(0, dp(10), 0, 0);
        parent.addView(valueLabel);
        SeekBar slider = new SeekBar(this);
        slider.setMax(100);
        slider.setProgress(initial);
        if (Build.VERSION.SDK_INT >= 21) {
            slider.getProgressDrawable().setTint(BLUE);
            slider.getThumb().setTint(SECONDARY);
        }
        slider.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar seekBar, int progress,
                                                     boolean fromUser) {
                valueLabel.setText(title + "  " + progress + "%");
                if (fromUser) listener.changed(progress);
            }
            @Override public void onStartTrackingTouch(SeekBar seekBar) { }
            @Override public void onStopTrackingTouch(SeekBar seekBar) { }
        });
        parent.addView(slider, matchWrap(0));
    }

    private void addGifSpeedSlider(LinearLayout parent) {
        TextView valueLabel = label("GIF 播放速度  " + gifSpeedPercent + "%", 13,
                INK, true);
        valueLabel.setPadding(0, dp(9), 0, 0);
        parent.addView(valueLabel);
        SeekBar slider = new SeekBar(this);
        slider.setMax(275);
        slider.setProgress(gifSpeedPercent - 25);
        if (Build.VERSION.SDK_INT >= 21) {
            slider.getProgressDrawable().setTint(BLUE);
            slider.getThumb().setTint(SECONDARY);
        }
        slider.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar seekBar, int progress,
                                                     boolean fromUser) {
                int speed = progress + 25;
                valueLabel.setText("GIF 播放速度  " + speed + "%");
                if (fromUser) gifSpeedPercent = speed;
            }
            @Override public void onStartTrackingTouch(SeekBar seekBar) { }
            @Override public void onStopTrackingTouch(SeekBar seekBar) {
                setGifSpeed(seekBar.getProgress() + 25, true);
            }
        });
        parent.addView(slider, matchWrap(0));
        TextView hint = label("100% 按 GIF 原时间轴播放；提高速度可补偿链路延迟，"
                + "实际上限仍受画面复杂度和 BLE/Wi‑Fi 带宽影响。", 12, MUTED, false);
        parent.addView(hint);
    }

    private void setGifSpeed(int speed, boolean notifyUser) {
        gifSpeedPercent = Math.max(25, Math.min(300, speed));
        preferences.edit().putInt("gif_speed_percent", gifSpeedPercent).apply();
        if (preferences.getBoolean("gif_service_running", false)) {
            Intent change = new Intent(this, GifPlaybackService.class)
                    .setAction(GifPlaybackService.ACTION_SPEED)
                    .putExtra(GifPlaybackService.EXTRA_SPEED_PERCENT, gifSpeedPercent);
            startService(change);
        }
        if (notifyUser) status("GIF 播放速度已设为 " + gifSpeedPercent + "%", true);
    }

    private void scheduleVisualStyleSync() {
        mainHandler.removeCallbacks(styleSyncRunnable);
        mainHandler.postDelayed(styleSyncRunnable, 220);
    }

    private void sendVisualStyle(boolean notifyUser) {
        int preset = visualPreset, wallpaper = wallpaperOpacity, panel = panelOpacity,
                hud = hudOpacity;
        if (selectedTransport() == 1) {
            if (!bleReady) {
                if (notifyUser) status("请先连接 BLE", false);
                return;
            }
            writeBleCommand(String.format(Locale.US, "STYLE:%d:%d:%d:%d", preset,
                    wallpaper, panel, hud));
            if (notifyUser) status("外观参数已通过 BLE 同步", true);
            return;
        }
        String endpoint = baseUrl() + "/api/display";
        worker.execute(() -> {
            try {
                JSONObject style = new JSONObject().put("preset", preset)
                        .put("wallpaperOpacity", wallpaper).put("panelOpacity", panel)
                        .put("hudOpacity", hud);
                String response = httpBlocking("POST", endpoint,
                        style.toString().getBytes(StandardCharsets.UTF_8),
                        "application/json", 12000);
                if (notifyUser) runOnUiThread(() -> status(
                        "外观参数已同步到设备\n" + response, true));
            } catch (Exception error) {
                if (notifyUser) runOnUiThread(() -> status(
                        "外观同步失败：" + error.getMessage(), false));
            }
        });
    }

    private LinearLayout card(LinearLayout parent, int[] gradient) {
        LinearLayout value = new LinearLayout(this);
        value.setOrientation(LinearLayout.VERTICAL);
        value.setPadding(dp(16), dp(16), dp(16), dp(16));
        GradientDrawable bg = gradient == null ? cardBackground()
                : new GradientDrawable(GradientDrawable.Orientation.TL_BR, gradient);
        bg.setCornerRadius(dp(12));
        bg.setAlpha(appGlassOpacity * 255 / 100);
        value.setBackground(bg);
        if (gradient == null) themedCards.add(value);
        parent.addView(value, matchWrap(dp(13)));
        return value;
    }

    private GradientDrawable cardBackground() {
        GradientDrawable background = roundRect(PANEL, 12,
                Color.argb(145, Color.red(BLUE), Color.green(BLUE), Color.blue(BLUE)));
        background.setAlpha(appGlassOpacity * 255 / 100);
        return background;
    }

    private void section(LinearLayout parent, String title, String subtitle) {
        parent.addView(label(title, 19, INK, true));
        TextView sub = label(subtitle, 12, MUTED, false);
        sub.setPadding(0, dp(2), 0, dp(10));
        parent.addView(sub);
    }

    private TextView label(String text, int size, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextSize(size);
        view.setTextColor(color);
        view.setLineSpacing(0, 1.16f);
        if (bold) view.setTypeface(view.getTypeface(), Typeface.BOLD);
        return view;
    }

    private EditText input(String value, String hint, boolean password) {
        EditText view = new EditText(this);
        view.setText(value == null ? "" : value);
        view.setHint(hint);
        view.setTextColor(INK);
        view.setHintTextColor(Color.rgb(139, 151, 172));
        view.setTextSize(14);
        view.setSingleLine(true);
        view.setPadding(dp(13), 0, dp(13), 0);
        view.setBackground(roundRect(Color.argb(235, 245, 241, 219), 8,
                Color.argb(190, Color.red(BLUE), Color.green(BLUE), Color.blue(BLUE))));
        if (password) view.setInputType(0x00000081);
        return view;
    }

    private Spinner spinner(String[] items) {
        Spinner spinner = new Spinner(this);
        spinner.setAdapter(new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_dropdown_item, items));
        spinner.setBackground(roundRect(Color.argb(235, 245, 241, 219), 8,
                Color.argb(190, Color.red(BLUE), Color.green(BLUE), Color.blue(BLUE))));
        return spinner;
    }
    private Spinner transportSelector() {
        Spinner selector = spinner(new String[]{"局域网 / Wi‑Fi", "Bluetooth LE"});
        selector.setSelection(preferences.getInt("transport", 0));
        selector.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view,
                                                  int position, long id) {
                preferences.edit().putInt("transport", position).apply();
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });
        return selector;
    }

    private CheckBox check(String text, boolean checked) {
        CheckBox box = new CheckBox(this);
        box.setText(text);
        box.setTextColor(INK);
        box.setTextSize(13);
        box.setChecked(checked);
        return box;
    }

    private Button button(String text, boolean primary, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(text);
        button.setTextSize(13);
        button.setAllCaps(false);
        button.setTextColor(primary ? Color.rgb(16, 16, 16) : INK);
        button.setBackground(roundRect(primary ? BLUE : Color.argb(225,
                        Color.red(PANEL), Color.green(PANEL), Color.blue(PANEL)),
                8, primary ? Color.TRANSPARENT : Color.argb(160, Color.red(MUTED),
                        Color.green(MUTED), Color.blue(MUTED))));
        button.setOnClickListener(listener);
        button.setStateListAnimator(null);
        return button;
    }

    private LinearLayout row(View... views) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        for (View view : views) {
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, dp(50), 1f);
            params.setMargins(dp(3), dp(4), dp(3), dp(4));
            row.addView(view, params);
        }
        return row;
    }

    private LinearLayout center(View view) {
        LinearLayout row = new LinearLayout(this);
        row.setGravity(Gravity.CENTER);
        row.addView(view, new LinearLayout.LayoutParams(dp(150), dp(48)));
        return row;
    }

    private LinearLayout.LayoutParams matchWrap(int top) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.topMargin = top;
        return params;
    }

    private GradientDrawable roundRect(int color, int radius, int stroke) {
        GradientDrawable value = new GradientDrawable();
        value.setColor(color);
        value.setCornerRadius(dp(radius));
        if (stroke != Color.TRANSPARENT) value.setStroke(dp(1), stroke);
        return value;
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private void status(String text, boolean good) {
        if (globalStatus != null) {
            globalStatus.setText(text);
            globalStatus.setTextColor(good ? GREEN : RED);
        }
    }
    private void toast(String text) { Toast.makeText(this, text, Toast.LENGTH_SHORT).show(); }
    private void showProgress(int value) {
        if (globalProgress != null) {
            globalProgress.setVisibility(View.VISIBLE);
            globalProgress.setProgress(value);
        }
    }
    private int selectedTransport() {
        return preferences.getInt("transport", 0);
    }
    private String baseUrl() {
        String value = deviceUrlInput == null ? preferences.getString("device_url",
                "http://192.168.4.1") : deviceUrlInput.getText().toString().trim();
        while (value.endsWith("/")) value = value.substring(0, value.length() - 1);
        preferences.edit().putString("device_url", value).apply();
        return value;
    }

    private interface ResultCallback { void done(String value); }
    private String httpBlocking(String method, String endpoint, byte[] body,
                                String type, int timeout) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(endpoint).openConnection();
        try {
            connection.setRequestMethod(method);
            connection.setConnectTimeout(6000);
            connection.setReadTimeout(timeout);
            connection.setUseCaches(false);
            if (body != null) {
                connection.setDoOutput(true);
                connection.setFixedLengthStreamingMode(body.length);
                connection.setRequestProperty("Content-Type",
                        type == null ? "application/octet-stream" : type);
                try (OutputStream output = connection.getOutputStream()) {
                    int offset = 0;
                    while (offset < body.length) {
                        int count = Math.min(8192, body.length - offset);
                        output.write(body, offset, count);
                        offset += count;
                    }
                }
            }
            int code = connection.getResponseCode();
            InputStream stream = code >= 200 && code < 300 ? connection.getInputStream()
                    : connection.getErrorStream();
            String result = stream == null ? "HTTP " + code
                    : new String(readAll(stream), StandardCharsets.UTF_8);
            if (code < 200 || code >= 300) throw new Exception(result);
            return result;
        } finally { connection.disconnect(); }
    }

    private void http(String method, String path, byte[] body, String type,
                      ResultCallback callback) {
        String endpoint = baseUrl() + path;
        worker.execute(() -> {
            try {
                String result = httpBlocking(method, endpoint, body, type, 30000);
                runOnUiThread(() -> callback.done(result));
            } catch (Exception error) {
                runOnUiThread(() -> status("请求失败：" + error.getMessage(), false));
            }
        });
    }

    private void fetchStatus() {
        requestDeviceStatus(false);
    }

    private void showIdleModeDialog() {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(dp(18), dp(6), dp(18), 0);
        idleTitleInput = input(preferences.getString("idle_title", "PHONE CONNECTED"),
                "屏幕标题（建议英文）", false);
        idleMessageInput = input(preferences.getString("idle_message", "READY FOR NOTICES"),
                "通知摘要（建议英文）", false);
        layout.addView(idleTitleInput, matchWrap(0));
        layout.addView(idleMessageInput, matchWrap(dp(6)));
        CheckBox notificationRelay = check("同步后续手机通知到闲置屏幕",
                preferences.getBoolean("notification_relay_enabled", false));
        layout.addView(notificationRelay, matchWrap(dp(5)));
        layout.addView(label("设备当前内置字体支持英文、数字和 - . :；中文会在屏幕上简化为空格。"
                + "APK 中仍保留原文字段。", 12, MUTED, false), matchWrap(dp(6)));
        new AlertDialog.Builder(this).setTitle("进入闲置信息模式")
                .setView(layout).setNegativeButton("取消", null)
                .setPositiveButton("显示到设备", (dialog, which) -> {
                    String title = idleTitleInput.getText().toString().trim();
                    String message = idleMessageInput.getText().toString().trim();
                    preferences.edit().putString("idle_title", title)
                            .putString("idle_message", message)
                            .putBoolean("notification_relay_enabled",
                                    notificationRelay.isChecked()).apply();
                    setOperationMode("idle", title, message);
                    if (notificationRelay.isChecked() && !notificationRelayGranted())
                        openNotificationAccess();
                }).show();
    }

    private boolean notificationRelayGranted() {
        String enabled = Settings.Secure.getString(getContentResolver(),
                "enabled_notification_listeners");
        return enabled != null && enabled.contains(new ComponentName(this,
                NotificationRelayService.class).flattenToString());
    }

    private void openNotificationAccess() {
        try {
            startActivity(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS));
            status("请允许 LabCapsule 读取通知；仅在闲置模式转发摘要", true);
        } catch (Exception error) {
            status("无法打开通知访问设置：" + error.getMessage(), false);
        }
    }

    private static String deviceDisplayText(String source, int maximum) {
        if (source == null) return "";
        StringBuilder result = new StringBuilder();
        boolean priorSpace = false;
        for (int index = 0; index < source.length() && result.length() < maximum; ++index) {
            char value = Character.toUpperCase(source.charAt(index));
            char output = ((value >= 'A' && value <= 'Z') ||
                    (value >= '0' && value <= '9') || value == '-' || value == '.' || value == ':')
                    ? value : ' ';
            if (output == ' ' && (result.length() == 0 || priorSpace)) continue;
            result.append(output);
            priorSpace = output == ' ';
        }
        return result.toString().trim();
    }

    private void setOperationMode(String mode, String title, String message) {
        boolean idle = "idle".equals(mode);
        String safeTitle = deviceDisplayText(title, 16);
        String safeMessage = deviceDisplayText(message, 32);
        if (safeTitle.isEmpty()) safeTitle = "DEVICE IDLE";
        if (safeMessage.isEmpty()) safeMessage = "READY FOR LINK";
        if (selectedTransport() == 1) {
            if (!bleReady) { status("请先连接 BLE", false); return; }
            preferences.edit().putString("operation_mode", mode).apply();
            if (idle) {
                writeBleCommand("NOTICE:" + safeTitle + "|" + safeMessage);
                mainHandler.postDelayed(() -> writeBleCommand("MODE:IDLE"), 750);
                mainHandler.postDelayed(this::fetchHardwareStatus, 1500);
            } else {
                writeBleCommand("MODE:EXPERIMENT");
                mainHandler.postDelayed(this::fetchHardwareStatus, 750);
            }
            status(idle ? "正在切换闲置信息模式…" : "正在切换实验直传模式…", true);
            return;
        }
        try {
            JSONObject payload = new JSONObject().put("mode", mode)
                    .put("title", title == null ? "" : title)
                    .put("message", message == null ? "" : message);
            http("POST", "/api/mode", payload.toString().getBytes(StandardCharsets.UTF_8),
                    "application/json", result -> {
                        preferences.edit().putString("operation_mode", mode).apply();
                        handleStatusPayload(result, true);
                        status(idle ? "设备已进入闲置信息模式" : "设备已进入实验直传模式", true);
                    });
        } catch (Exception error) {
            status("模式参数无效：" + error.getMessage(), false);
        }
    }

    private void fetchHardwareStatus() {
        if (selectedTransport() == 1) {
            writeBleCommand("HARDWARE", true);
        } else {
            requestDeviceStatus(true);
        }
    }

    private void handleHardwarePayload(JSONObject hardware, String mode) {
        if (hardware == null) return;
        long internalFree = hardware.optLong("internalFree");
        long internalTotal = hardware.optLong("internalTotal");
        long psramFree = hardware.optLong("psramFree");
        long psramTotal = hardware.optLong("psramTotal");
        long storageUsed = hardware.optLong("storageUsed");
        long storageCapacity = hardware.optLong("storageCapacity");
        long uptime = hardware.optLong("uptimeSeconds");
        int ramUsed = internalTotal <= 0 ? 0 :
                (int)((internalTotal - internalFree) * 100 / internalTotal);
        int psramUsed = psramTotal <= 0 ? 0 :
                (int)((psramTotal - psramFree) * 100 / psramTotal);
        int storagePercent = storageCapacity <= 0 ? 0 :
                (int)(storageUsed * 100 / storageCapacity);
        String summary = "内部 RAM " + ramUsed + "% · PSRAM " + psramUsed +
                "% · 实验存储 " + storagePercent + "%\n运行 " + uptime +
                " 秒 · BLE " + (hardware.optBoolean("bleConnected") ? "在线" : "离线") +
                " · Wi‑Fi " + (hardware.optBoolean("staConnected") ? "在线" : "离线") +
                " · 远程 " + (hardware.optBoolean("remoteConnected") ? "在线" : "离线");
        preferences.edit().putString("hardware_summary", summary)
                .putString("operation_mode", mode == null ? "experiment" : mode).apply();
        if (hardwareUsageState != null) {
            hardwareUsageState.setText(summary);
            hardwareUsageState.setTextColor(GREEN);
        }
        if (operationModeState != null) {
            boolean idle = "idle".equals(mode);
            operationModeState.setText(idle ? "● 闲置信息模式" : "● 实验直传模式");
            operationModeState.setTextColor(idle ? BLUE : GREEN);
        }
    }

    private void requestDeviceStatus(boolean quiet) {
        if (!quiet) status("正在连接设备…", true);
        if (selectedTransport() == 1) {
            writeBleCommand("STATUS", quiet);
            return;
        }
        String endpoint = baseUrl() + "/api/status";
        worker.execute(() -> {
            try {
                String result = httpBlocking("GET", endpoint, null, null, 8000);
                runOnUiThread(() -> handleStatusPayload(result, quiet));
            } catch (Exception error) {
                if (!quiet) runOnUiThread(() ->
                        status("请求失败：" + error.getMessage(), false));
            }
        });
    }
    private void handleStatusPayload(String result, boolean quiet) {
        try {
            JSONObject root = new JSONObject(result);
            JSONObject network = root.optJSONObject("network");
            if (network != null) renderExternalWifi(network.optBoolean("staConfigured"),
                    network.optBoolean("staConnected"),
                    network.optString("staIp", "0.0.0.0"),
                    network.optString("recoveryAp", "LabCapsule"));
            if (network != null && !network.optBoolean("recoveryApActive", true) &&
                    externalWifiHint != null) {
                externalWifiHint.append("\n恢复热点当前未启用；请点击“恢复设备热点”。");
            }
            if (network != null && !network.optBoolean("staConnected") &&
                    network.optInt("lastDisconnectReason", 0) != 0 &&
                    externalWifiHint != null) {
                externalWifiHint.append("\n最近失败：" + wifiReasonText(
                        network.optInt("lastDisconnectReason", 0)));
            }
            JSONObject device = root.optJSONObject("device");
            if (device != null) preferences.edit().putLong("last_sample_count",
                    device.optLong("samples", preferences.getLong("last_sample_count", 0))).apply();
            if (device != null) {
                String operationMode = device.optString("operationMode", "experiment");
                JSONObject hardware = device.optJSONObject("hardware");
                if (hardware != null) handleHardwarePayload(hardware, operationMode);
                else {
                    preferences.edit().putString("operation_mode", operationMode).apply();
                    if (operationModeState != null) {
                        boolean idle = "idle".equals(operationMode);
                        operationModeState.setText(idle ? "● 闲置信息模式" :
                                "● 实验直传模式");
                        operationModeState.setTextColor(idle ? BLUE : GREEN);
                    }
                }
            }
            if (device != null && device.has("offlineSessions")) {
                JSONObject offline = new JSONObject()
                        .put("sessions", device.optLong("offlineSessions"))
                        .put("samples", device.optLong("offlineSamples"))
                        .put("recording", device.optBoolean("offlineRecording"));
                handleOfflinePayload(offline);
            }
            JSONObject style = device == null ? null : device.optJSONObject("style");
            if (style != null) {
                int previousPreset = visualPreset;
                applyThemePalette(style.optInt("preset", visualPreset));
                wallpaperOpacity = style.optInt("wallpaperOpacity", wallpaperOpacity);
                panelOpacity = style.optInt("panelOpacity", panelOpacity);
                hudOpacity = style.optInt("hudOpacity", hudOpacity);
                preferences.edit().putInt("visual_preset", visualPreset)
                        .putInt("wallpaper_opacity", wallpaperOpacity)
                        .putInt("panel_opacity", panelOpacity)
                        .putInt("hud_opacity", hudOpacity).apply();
                refreshThemeSurfaces();
                if (previousPreset != visualPreset && !screenMonitorActive)
                    mainHandler.post(() -> showSection(currentSection));
            }
            if (device != null && mediaPreview instanceof WallpaperPreview) {
                ((WallpaperPreview) mediaPreview).setDeviceState(
                        device.optString("state", "READY"),
                        device.optString("view", "home"),
                        device.optString("mpu", "unknown"),
                        device.optBoolean("backlight", true));
            }
            if (screenMonitorState != null && screenMonitorActive) {
                screenMonitorState.setText("● 实时同步中 · " +
                        (device == null ? "等待设备状态" : device.optString("view", "home") +
                                " / " + device.optString("state", "READY")));
                screenMonitorState.setTextColor(GREEN);
            }
            if (!quiet) status("设备在线 · staConnected=" +
                    (network != null && network.optBoolean("staConnected")) +
                    " · staIp=" + (network == null ? "未知" :
                    network.optString("staIp", "0.0.0.0")), true);
            if (!quiet && selectedTransport() == 1 && device != null &&
                    device.optJSONObject("hardware") == null) {
                mainHandler.postDelayed(this::fetchHardwareStatus, 450);
            }
        } catch (Exception error) {
            if (!quiet) status("设备在线，但状态格式无法解析：" + error.getMessage(), false);
        }
    }
    private void renderExternalWifi(boolean configured, boolean connected, String ip,
                                    String recoveryAp) {
        preferences.edit().putBoolean("sta_configured", configured)
                .putBoolean("sta_connected", connected)
                .putString("sta_ip", ip == null ? "0.0.0.0" : ip)
                .putString("recovery_ap", recoveryAp == null ? "LabCapsule" : recoveryAp)
                .apply();
        if (connected && ip != null && !ip.isEmpty() && !"0.0.0.0".equals(ip)) {
            lastStationIp = ip;
            if (externalWifiState != null) {
                externalWifiState.setText("● 已连接外部 Wi‑Fi");
                externalWifiState.setTextColor(GREEN);
            }
            if (externalWifiIp != null) externalWifiIp.setText("局域网 IP：http://" + ip);
            if (externalWifiHint != null) externalWifiHint.setText(
                    "连接成功。手机保持正常联网 Wi‑Fi，点击“使用此局域网 IP”即可。\n"
                            + "staConnected=true · staIp=" + ip);
        } else if (configured) {
            lastStationIp = null;
            if (externalWifiState != null) {
                externalWifiState.setText("● 已保存配置，正在连接或连接失败");
                externalWifiState.setTextColor(Color.rgb(213, 132, 24));
            }
            if (externalWifiIp != null) externalWifiIp.setText("局域网 IP：尚未获取");
            if (externalWifiHint != null) externalWifiHint.setText(
                    "staConnected=false · staIp=0.0.0.0\n"
                            + "请确认路由器开启 2.4 GHz、SSID/密码正确；可直接用 BLE 重配。"
                            + "恢复热点：" + recoveryAp);
        } else {
            lastStationIp = null;
            if (externalWifiState != null) {
                externalWifiState.setText("● 尚未配置外部 Wi‑Fi");
                externalWifiState.setTextColor(MUTED);
            }
            if (externalWifiIp != null) externalWifiIp.setText("局域网 IP：尚未获取");
            if (externalWifiHint != null) externalWifiHint.setText(
                    "staConnected=false · staIp=0.0.0.0\n"
                            + "连接 BLE 后点击“蓝牙一键配网”，无需连接设备热点。");
        }
    }
    private String wifiReasonText(int reason) {
        if (reason == 201) return "未找到该 2.4 GHz 网络（代码 201）";
        if (reason == 202) return "密码或认证失败（代码 202）";
        if (reason == 203) return "路由器拒绝关联（代码 203）";
        if (reason == 204) return "握手超时（代码 204）";
        return "Wi‑Fi 断开代码 " + reason;
    }
    private void useStationIp() {
        if (lastStationIp == null || lastStationIp.isEmpty()) {
            toast("设备还没有获得外部 Wi‑Fi IP"); return;
        }
        String url = "http://" + lastStationIp;
        preferences.edit().putString("device_url", url).apply();
        if (deviceUrlInput != null) deviceUrlInput.setText(url);
        status("设备地址已切换为 " + url, true);
    }
    private void fetchSensors() {
        status("正在扫描扩展总线…", true);
        if (selectedTransport() == 1) {
            writeBleCommand("SENSORS");
            return;
        }
        http("GET", "/api/sensors", null, null,
                this::handleSensorPayload);
    }
    private void handleSensorPayload(String payload) {
        try {
            JSONObject root = new JSONObject(payload);
            JSONObject hub = root.optJSONObject("hub");
            JSONObject source = hub == null ? root : hub;
            JSONArray sensors = source.optJSONArray("sensors");
            StringBuilder result = new StringBuilder("I²C 扫描完成");
            int found = root.optInt("count", -1);
            if (sensors != null) {
                if (found < 0) {
                    found = 0;
                    for (int i = 0; i < sensors.length(); ++i)
                        if (sensors.getJSONObject(i).optBoolean("detected")) ++found;
                }
                result.append(" · 发现 ").append(found).append(" 个响应设备");
                for (int i = 0; i < sensors.length(); ++i) {
                    JSONObject sensor = sensors.getJSONObject(i);
                    if (hub != null && !sensor.optBoolean("detected")) continue;
                    String address = sensor.optString("address", "?");
                    if (hub != null && sensor.has("address"))
                        address = String.format(Locale.US, "0x%02X",
                                sensor.optInt("address"));
                    result.append("\n• ").append(sensor.optString("name",
                            sensor.optString("id", "未知设备"))).append(" · ").append(address);
                }
            }
            if (found == 0) result.append("\n请检查 SDA=GPIO8、SCL=GPIO9、3V3 与共地。");
            if (sensorResult != null) {
                sensorResult.setText(result.toString());
                sensorResult.setTextColor(found > 0 ? GREEN : RED);
            }
            status(result.toString(), found > 0);
        } catch (Exception error) {
            status("扫描结果无法解析：" + error.getMessage(), false);
        }
    }
    private void sendAction(String action) {
        if (selectedTransport() == 1) { writeBleCommand(action); return; }
        try {
            http("POST", "/api/control?action=" + URLEncoder.encode(action, "UTF-8"),
                    new byte[0], "application/octet-stream",
                    ignored -> status("已执行：" + action, true));
        } catch (Exception error) { status(error.getMessage(), false); }
    }

    private void chooseFirmware() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("application/octet-stream");
        startActivityForResult(intent, REQUEST_FIRMWARE);
    }
    private void chooseMedia() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("image/*");
        startActivityForResult(intent, REQUEST_MEDIA);
    }
    private void chooseCsv() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("text/*");
        startActivityForResult(intent, REQUEST_CSV);
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (resultCode != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData();
        worker.execute(() -> {
            try (InputStream input = getContentResolver().openInputStream(uri)) {
                byte[] bytes = readAll(input);
                String name = displayName(uri);
                if (requestCode == REQUEST_FIRMWARE) {
                    runOnUiThread(() -> {
                        selectedFirmware = bytes;
                        if (firmwareInfo != null) firmwareInfo.setText(name + " · " + bytes.length + " bytes");
                    });
                } else if (requestCode == REQUEST_CSV) {
                    String analysis = analyzeCsv(new String(bytes, StandardCharsets.UTF_8), name);
                    preferences.edit().putString("last_analysis", analysis).apply();
                    runOnUiThread(() -> {
                        if (analysisResultView != null) {
                            analysisResultView.setText(analysis);
                            analysisResultView.setTextColor(INK);
                        }
                        status("CSV 分析完成", true);
                    });
                } else {
                    Movie movie = Movie.decodeByteArray(bytes, 0, bytes.length);
                    Bitmap bitmap = decodeStaticForCrop(bytes);
                    if (movie == null && bitmap == null) throw new Exception("不支持的图片格式");
                    Movie animated = movie != null && movie.duration() > 0 ? movie : null;
                    Bitmap cropSource = animated == null ? bitmap : renderMovieSourceFrame(animated, 0);
                    runOnUiThread(() -> showCropEditor(cropSource, animated, name));
                }
            } catch (Exception error) {
                runOnUiThread(() -> status("文件处理失败：" + error.getMessage(), false));
            }
        });
    }

    private String analyzeCsv(String text, String name) throws Exception {
        String[] lines = text.replace("\r", "").split("\n");
        ArrayList<double[]> rows = new ArrayList<>();
        for (String line : lines) {
            if (line.trim().isEmpty()) continue;
            String[] fields = line.split(",");
            int offset = fields.length > 0 && "DATA".equalsIgnoreCase(fields[0].trim()) ? 1 : 0;
            if (fields.length - offset < 7) continue;
            try {
                double[] row = new double[7];
                for (int column = 0; column < 7; ++column)
                    row[column] = Double.parseDouble(fields[offset + column].trim());
                rows.add(row);
                if (rows.size() >= 100000) break;
            } catch (NumberFormatException ignored) { }
        }
        if (rows.size() < 16) throw new Exception("有效六轴样本少于 16 条");
        double[] sumSquares = new double[6];
        double[] peaks = new double[6];
        for (double[] row : rows) for (int channel = 0; channel < 6; ++channel) {
            double value = row[channel + 1];
            sumSquares[channel] += value * value;
            peaks[channel] = Math.max(peaks[channel], Math.abs(value));
        }
        int fftSize = 1;
        while (fftSize * 2 <= rows.size() && fftSize < 4096) fftSize *= 2;
        double[] real = new double[fftSize], imaginary = new double[fftSize];
        double mean = 0;
        for (int index = 0; index < fftSize; ++index) {
            double[] row = rows.get(index);
            real[index] = Math.sqrt(row[1] * row[1] + row[2] * row[2] + row[3] * row[3]);
            mean += real[index];
        }
        mean /= fftSize;
        for (int index = 0; index < fftSize; ++index) {
            real[index] = (real[index] - mean) *
                    (.5 - .5 * Math.cos(2 * Math.PI * index / (fftSize - 1)));
        }
        fft(real, imaginary);
        int dominantBin = 1;
        double dominantPower = 0;
        for (int bin = 1; bin < fftSize / 2; ++bin) {
            double power = real[bin] * real[bin] + imaginary[bin] * imaginary[bin];
            if (power > dominantPower) { dominantPower = power; dominantBin = bin; }
        }
        double elapsedUs = rows.get(fftSize - 1)[0] - rows.get(0)[0];
        double sampleRate = elapsedUs > 0 ? (fftSize - 1) * 1000000.0 / elapsedUs : 0;
        double dominantFrequency = sampleRate * dominantBin / fftSize;
        String[] channels = {"AX", "AY", "AZ", "GX", "GY", "GZ"};
        StringBuilder result = new StringBuilder();
        result.append(name).append("\n样本：").append(rows.size())
                .append(" · 估算采样率：").append(String.format(Locale.US, "%.1f Hz", sampleRate))
                .append("\n加速度合量主频：")
                .append(String.format(Locale.US, "%.2f Hz", dominantFrequency));
        for (int channel = 0; channel < 6; ++channel) {
            result.append("\n").append(channels[channel]).append("  RMS=")
                    .append(String.format(Locale.US, "%.4f", Math.sqrt(
                            sumSquares[channel] / rows.size())))
                    .append("  Peak=").append(String.format(Locale.US, "%.4f",
                            peaks[channel]));
        }
        return result.toString();
    }

    private static void fft(double[] real, double[] imaginary) {
        int size = real.length;
        for (int index = 1, reverse = 0; index < size; ++index) {
            int bit = size >> 1;
            while ((reverse & bit) != 0) { reverse ^= bit; bit >>= 1; }
            reverse ^= bit;
            if (index < reverse) {
                double temporary = real[index]; real[index] = real[reverse]; real[reverse] = temporary;
                temporary = imaginary[index]; imaginary[index] = imaginary[reverse];
                imaginary[reverse] = temporary;
            }
        }
        for (int length = 2; length <= size; length <<= 1) {
            double angle = -2 * Math.PI / length;
            double rootReal = Math.cos(angle), rootImaginary = Math.sin(angle);
            for (int start = 0; start < size; start += length) {
                double unitReal = 1, unitImaginary = 0;
                for (int offset = 0; offset < length / 2; ++offset) {
                    int even = start + offset, odd = even + length / 2;
                    double oddReal = real[odd] * unitReal - imaginary[odd] * unitImaginary;
                    double oddImaginary = real[odd] * unitImaginary + imaginary[odd] * unitReal;
                    real[odd] = real[even] - oddReal;
                    imaginary[odd] = imaginary[even] - oddImaginary;
                    real[even] += oddReal;
                    imaginary[even] += oddImaginary;
                    double nextReal = unitReal * rootReal - unitImaginary * rootImaginary;
                    unitImaginary = unitReal * rootImaginary + unitImaginary * rootReal;
                    unitReal = nextReal;
                }
            }
        }
    }

    private void shareAnalysis() {
        String result = preferences.getString("last_analysis", "");
        if (result.isEmpty()) { toast("请先导入 CSV"); return; }
        Intent share = new Intent(Intent.ACTION_SEND).setType("text/plain")
                .putExtra(Intent.EXTRA_SUBJECT, "LabCapsule 六轴分析")
                .putExtra(Intent.EXTRA_TEXT, result);
        startActivity(Intent.createChooser(share, "分享分析结果"));
    }

    private void refreshOfflineStore() {
        status("正在读取设备离线缓存…", true);
        if (selectedTransport() == 1) {
            writeBleCommand("OFFLINE:INFO");
        } else {
            fetchStatus();
        }
    }

    private void handleOfflinePayload(JSONObject offline) {
        if (offline == null) return;
        long sessions = offline.optLong("sessions", offline.optLong("offlineSessions", 0));
        long samples = offline.optLong("samples", offline.optLong("offlineSamples", 0));
        long current = offline.optLong("currentSamples", 0);
        long dropped = offline.optLong("droppedSamples", 0);
        long used = offline.optLong("bytesUsed", 0);
        long capacity = offline.optLong("bytesCapacity", 0);
        boolean recording = offline.optBoolean("recording",
                offline.optBoolean("offlineRecording", false));
        StringBuilder text = new StringBuilder();
        text.append(recording ? "● 正在实验并缓存" : "● 缓存可用")
                .append("\n离线实验：").append(sessions)
                .append(" · 已保存样本：").append(samples);
        if (current > 0) text.append(" · 本轮：").append(current);
        if (capacity > 0) text.append("\n空间：").append(formatBytes(used))
                .append(" / ").append(formatBytes(capacity));
        if (dropped > 0) text.append("\n警告：队列丢弃 ").append(dropped).append(" 个样本");
        if (offline.optBoolean("full", false)) text.append("\n警告：设备缓存空间已满");
        preferences.edit().putLong("offline_sessions", sessions)
                .putLong("offline_samples", samples).apply();
        if (offlineStoreState != null) {
            offlineStoreState.setText(text.toString());
            offlineStoreState.setTextColor(dropped > 0 || offline.optBoolean("full", false)
                    ? RED : GREEN);
        }
        if (currentSection == 2) status(text.toString(), true);
    }

    private static String formatBytes(long bytes) {
        if (bytes >= 1024L * 1024L)
            return String.format(Locale.US, "%.1f MB", bytes / (1024.0 * 1024.0));
        if (bytes >= 1024L) return String.format(Locale.US, "%.1f KB", bytes / 1024.0);
        return bytes + " B";
    }

    private File newOfflineSyncFile() throws IOException {
        File directory = new File(getFilesDir(), "experiment-sync");
        if (!directory.exists() && !directory.mkdirs())
            throw new IOException("无法创建设备数据目录");
        return new File(directory, "offline-" + System.currentTimeMillis() + ".lcb");
    }

    private void syncOfflineData() {
        if ("offline_open".equals(bleTransferPhase) ||
                "offline_read".equals(bleTransferPhase)) {
            status("设备缓存正在同步", false); return;
        }
        try {
            offlineSyncFile = newOfflineSyncFile();
            offlineSyncOutput = new BufferedOutputStream(new FileOutputStream(offlineSyncFile));
            offlineSyncBytes = 0;
        } catch (Exception error) {
            status("无法准备同步文件：" + error.getMessage(), false); return;
        }
        showProgress(0);
        if (selectedTransport() == 1) {
            if (!bleReady || experimentDataCharacteristic == null ||
                    !"idle".equals(bleTransferPhase)) {
                closeOfflineSync(true);
                status("请先连接支持离线缓存的 V0.5 BLE 固件", false); return;
            }
            bleTransferPhase = "offline_open";
            if (!writeCharacteristic(commandCharacteristic,
                    "OFFLINE:OPEN".getBytes(StandardCharsets.UTF_8))) {
                bleTransferPhase = "idle";
                closeOfflineSync(true);
                status("无法打开设备离线缓存", false);
            } else status("BLE 正在同步离线实验…", true);
        } else {
            worker.execute(this::syncOfflineHttp);
        }
    }

    private void syncOfflineHttp() {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection)new URL(baseUrl() + "/api/offline").openConnection();
            connection.setRequestMethod("GET");
            connection.setConnectTimeout(8000);
            connection.setReadTimeout(60000);
            int code = connection.getResponseCode();
            if (code < 200 || code >= 300) throw new IOException("HTTP " + code);
            try (InputStream input = new BufferedInputStream(connection.getInputStream())) {
                byte[] buffer = new byte[8192];
                int count;
                while ((count = input.read(buffer)) >= 0) {
                    if (count == 0) continue;
                    offlineSyncOutput.write(buffer, 0, count);
                    offlineSyncBytes += count;
                }
            }
            offlineSyncOutput.close();
            offlineSyncOutput = null;
            finishOfflineSync();
        } catch (Exception error) {
            closeOfflineSync(true);
            runOnUiThread(() -> status("离线数据同步失败：" + error.getMessage(), false));
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private void closeOfflineSync(boolean deletePartial) {
        try { if (offlineSyncOutput != null) offlineSyncOutput.close(); }
        catch (Exception ignored) { }
        offlineSyncOutput = null;
        if (deletePartial && offlineSyncFile != null) offlineSyncFile.delete();
    }

    private void finishOfflineSync() {
        final File file = offlineSyncFile;
        final long bytes = offlineSyncBytes;
        if (file == null || bytes == 0) {
            closeOfflineSync(true);
            runOnUiThread(() -> status("设备中没有可同步的离线实验", true));
            return;
        }
        worker.execute(() -> {
            try {
                String result = analyzeOfflineBinary(file);
                preferences.edit().putString("last_analysis", result)
                        .putString("last_offline_file", file.getAbsolutePath()).apply();
                runOnUiThread(() -> {
                    if (analysisResultView != null) {
                        analysisResultView.setText(result);
                        analysisResultView.setTextColor(INK);
                    }
                    showProgress(100);
                    status("离线数据已同步并分析 · " + formatBytes(bytes), true);
                });
            } catch (Exception error) {
                runOnUiThread(() -> status("离线数据格式错误：" + error.getMessage(), false));
            }
        });
    }

    private void confirmClearOfflineData() {
        new AlertDialog.Builder(this).setTitle("清空设备离线数据？")
                .setMessage("请先确认已经同步。此操作无法撤销，实验进行中不能清空。")
                .setNegativeButton("取消", null)
                .setPositiveButton("清空", (dialog, which) -> clearOfflineData()).show();
    }

    private void clearOfflineData() {
        if (selectedTransport() == 1) {
            writeBleCommand("OFFLINE:CLEAR");
        } else {
            http("POST", "/api/offline", new byte[0], "application/octet-stream",
                    ignored -> {
                        if (offlineStoreState != null)
                            offlineStoreState.setText("设备离线缓存已清空");
                        status("设备离线缓存已清空", true);
                    });
        }
    }

    private String analyzeOfflineBinary(File source) throws Exception {
        int sessions = 0;
        long totalSamples = 0;
        StringBuilder csv = new StringBuilder();
        try (InputStream input = new BufferedInputStream(new FileInputStream(source))) {
            byte[] header = new byte[32];
            byte[] sample = new byte[16];
            while (readFullyOrEof(input, header)) {
                if (littleInt(header, 0) != 0x3142434C || littleShort(header, 4) != 1 ||
                        littleShort(header, 6) != 32) throw new IOException("LCB1 头无效");
                long rate = unsignedInt(littleInt(header, 12));
                long count = unsignedInt(littleInt(header, 20));
                ++sessions;
                totalSamples += count;
                for (long index = 0; index < count; ++index) {
                    if (!readFullyOrEof(input, sample)) throw new EOFException("样本不完整");
                    if (sessions == 1 && index < 100000) {
                        long elapsed = unsignedInt(littleInt(sample, 0));
                        csv.append(elapsed);
                        for (int axis = 0; axis < 6; ++axis) {
                            short packed = (short)littleShort(sample, 4 + axis * 2);
                            double scale = axis < 3 ? 4096.0 : 16.0;
                            csv.append(',').append(String.format(Locale.US, "%.5f",
                                    packed / scale));
                        }
                        csv.append('\n');
                    }
                }
                if (rate == 0) throw new IOException("采样率无效");
            }
        }
        if (sessions == 0) throw new IOException("没有完整实验");
        return "设备离线同步：" + sessions + " 组，共 " + totalSamples + " 个样本\n"
                + "本地文件：" + source.getAbsolutePath() + "\n"
                + "以下分析使用第一组实验：\n" + analyzeCsv(csv.toString(), source.getName());
    }

    private static boolean readFullyOrEof(InputStream input, byte[] buffer) throws IOException {
        int offset = 0;
        while (offset < buffer.length) {
            int count = input.read(buffer, offset, buffer.length - offset);
            if (count < 0) {
                if (offset == 0) return false;
                throw new EOFException("文件被截断");
            }
            offset += count;
        }
        return true;
    }

    private static int littleShort(byte[] value, int offset) {
        return (value[offset] & 0xFF) | ((value[offset + 1] & 0xFF) << 8);
    }

    private static int littleInt(byte[] value, int offset) {
        return littleShort(value, offset) | (littleShort(value, offset + 2) << 16);
    }

    private static long unsignedInt(int value) { return value & 0xFFFFFFFFL; }

    private String displayName(Uri uri) {
        try (Cursor cursor = getContentResolver().query(uri,
                new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) return cursor.getString(0);
        } catch (Exception ignored) { }
        return uri.getLastPathSegment() == null ? "file" : uri.getLastPathSegment();
    }
    private static Bitmap decodeStaticForCrop(byte[] bytes) {
        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        BitmapFactory.decodeByteArray(bytes, 0, bytes.length, bounds);
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null;
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inSampleSize = 1;
        int largest = Math.max(bounds.outWidth, bounds.outHeight);
        while (largest / options.inSampleSize > 2048) options.inSampleSize *= 2;
        options.inPreferredConfig = Bitmap.Config.ARGB_8888;
        return BitmapFactory.decodeByteArray(bytes, 0, bytes.length, options);
    }
    private void showCropEditor(Bitmap source, Movie movie, String name) {
        if (source == null) { status("无法生成裁剪预览", false); return; }
        stopGifStreamSilently();
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(dp(16), dp(8), dp(16), 0);
        TextView guide = label("单指拖动、双指缩放，也可使用下方缩放滑杆。白色框就是设备最终显示区域。", 13,
                MUTED, false);
        guide.setPadding(0, 0, 0, dp(8));
        layout.addView(guide);
        CropImageView editor = new CropImageView(this);
        editor.setImage(source);
        layout.addView(editor, new LinearLayout.LayoutParams(-1, dp(350)));
        TextView zoomValue = label("裁剪缩放  100%", 13, INK, true);
        zoomValue.setPadding(0, dp(7), 0, 0);
        layout.addView(zoomValue);
        SeekBar zoomSlider = new SeekBar(this);
        zoomSlider.setMax(700);
        zoomSlider.setProgress(0);
        if (Build.VERSION.SDK_INT >= 21) {
            zoomSlider.getProgressDrawable().setTint(BLUE);
            zoomSlider.getThumb().setTint(SECONDARY);
        }
        zoomSlider.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar seekBar, int progress,
                                                     boolean fromUser) {
                int percent = progress + 100;
                zoomValue.setText("裁剪缩放  " + percent + "%");
                if (fromUser) editor.setZoomPercent(percent);
            }
            @Override public void onStartTrackingTouch(SeekBar seekBar) { }
            @Override public void onStopTrackingTouch(SeekBar seekBar) { }
        });
        layout.addView(zoomSlider, matchWrap(0));
        AlertDialog cropDialog = new AlertDialog.Builder(this).setTitle("裁剪为 240 × 320")
                .setView(layout).setNegativeButton("取消", null)
                .setNeutralButton("复位", null)
                .setPositiveButton("确认裁剪", (dialog, which) -> {
                    RectF crop = editor.getSourceCrop();
                    Bitmap preview = cropBitmap(source, crop, 240, 320);
                    selectedCropSource = source;
                    selectedCropRect = new RectF(crop);
                    selectedMovie = movie;
                    selectedMediaName = name;
                    selectedPreview = preview;
                    lastGifComparisonFrame = null;
                    if (mediaPreview != null) mediaPreview.setImageBitmap(preview);
                    if (mediaInfo != null) mediaInfo.setText(name + " · 壁纸裁剪 240×320 · " +
                            (movie == null ? "RGB565 持久壁纸" : "GIF 智能流媒体"));
                    status("裁剪已确认；当前显示的是壁纸 + HUD 合成预览", true);
                }).create();
        cropDialog.setOnShowListener(dialog -> cropDialog.getButton(AlertDialog.BUTTON_NEUTRAL)
                .setOnClickListener(v -> {
                    editor.resetImage();
                    zoomSlider.setProgress(0);
                    zoomValue.setText("裁剪缩放  100%");
                }));
        cropDialog.show();
    }
    private void reopenCropEditor() {
        if (selectedCropSource == null) { toast("请先选择媒体"); return; }
        showCropEditor(selectedCropSource, selectedMovie,
                selectedMediaName == null ? "媒体" : selectedMediaName);
    }
    private static Bitmap cropBitmap(Bitmap source, RectF crop, int width, int height) {
        Bitmap result = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(result);
        Rect sourceRect = new Rect(Math.max(0, (int) Math.floor(crop.left)),
                Math.max(0, (int) Math.floor(crop.top)),
                Math.min(source.getWidth(), (int) Math.ceil(crop.right)),
                Math.min(source.getHeight(), (int) Math.ceil(crop.bottom)));
        canvas.drawBitmap(source, sourceRect, new RectF(0, 0, width, height),
                new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG));
        return result;
    }
    private static Bitmap renderMovieSourceFrame(Movie movie, int timeMs) {
        Bitmap result = Bitmap.createBitmap(Math.max(1, movie.width()),
                Math.max(1, movie.height()), Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(result);
        canvas.drawColor(Color.BLACK);
        movie.setTime(timeMs);
        movie.draw(canvas, 0, 0, new Paint(Paint.ANTI_ALIAS_FLAG |
                Paint.FILTER_BITMAP_FLAG));
        return result;
    }
    private Bitmap renderCroppedMovieFrame(Movie movie, int timeMs) {
        Bitmap source = renderMovieSourceFrame(movie, timeMs);
        RectF crop = selectedCropRect == null
                ? new RectF(0, 0, source.getWidth(), source.getHeight())
                : new RectF(selectedCropRect);
        Bitmap result = cropBitmap(source, crop, 240, 320);
        source.recycle();
        return result;
    }
    private static byte[] bitmapToRgb565(Bitmap bitmap) {
        int[] pixels = new int[240 * 320];
        bitmap.getPixels(pixels, 0, 240, 0, 0, 240, 320);
        byte[] output = new byte[240 * 320 * 2];
        int index = 0;
        for (int pixel : pixels) {
            int value = ((Color.red(pixel) & 0xF8) << 8) |
                    ((Color.green(pixel) & 0xFC) << 3) | (Color.blue(pixel) >> 3);
            output[index++] = (byte) (value >> 8);
            output[index++] = (byte) value;
        }
        return output;
    }

    private static byte[] bitmapToRgb332(Bitmap bitmap) {
        int[] pixels = new int[240 * 320];
        bitmap.getPixels(pixels, 0, 240, 0, 0, 240, 320);
        byte[] output = new byte[pixels.length];
        for (int i = 0; i < pixels.length; ++i) {
            int pixel = pixels[i];
            output[i] = (byte) ((Color.red(pixel) & 0xE0) |
                    ((Color.green(pixel) & 0xE0) >> 3) | (Color.blue(pixel) >> 6));
        }
        return output;
    }

    private static final class MediaPacket {
        byte[] data;
        byte[] comparisonFrame;
        String encoding;
        int x, y, width, height;
        boolean unchanged;
        String description() {
            if (unchanged) return "画面未变化，跳过传输";
            int saved = 100 - data.length * 100 / (240 * 320 * 2);
            return String.format(Locale.US, "%s · %dx%d · %,d B · 比整帧减少 %d%%",
                    encoding.toUpperCase(Locale.ROOT), width, height, data.length, saved);
        }
        String httpPath(int duration) {
            return String.format(Locale.US,
                    "/api/media/frame?duration=%d&enc=%s&x=%d&y=%d&w=%d&h=%d",
                    duration, encoding, x, y, width, height);
        }
    }

    private static MediaPacket encodeMediaPacket(Bitmap bitmap, byte[] previous,
                                                 boolean gifOptimized) {
        int bytesPerPixel = gifOptimized ? 1 : 2;
        byte[] full = gifOptimized ? bitmapToRgb332(bitmap) : bitmapToRgb565(bitmap);
        MediaPacket packet = new MediaPacket();
        packet.comparisonFrame = full;
        int minX = 240, minY = 320, maxX = -1, maxY = -1;
        if (previous == null || previous.length != full.length) {
            minX = 0; minY = 0; maxX = 239; maxY = 319;
        } else {
            for (int pixel = 0; pixel < 240 * 320; ++pixel) {
                int offset = pixel * bytesPerPixel;
                boolean changed = false;
                for (int byteIndex = 0; byteIndex < bytesPerPixel; ++byteIndex) {
                    if (full[offset + byteIndex] != previous[offset + byteIndex]) {
                        changed = true; break;
                    }
                }
                if (changed) {
                    int x = pixel % 240, y = pixel / 240;
                    if (x < minX) minX = x;
                    if (x > maxX) maxX = x;
                    if (y < minY) minY = y;
                    if (y > maxY) maxY = y;
                }
            }
        }
        if (maxX < minX || maxY < minY) {
            packet.unchanged = true;
            packet.data = new byte[0];
            return packet;
        }
        packet.x = minX;
        packet.y = minY;
        packet.width = maxX - minX + 1;
        packet.height = maxY - minY + 1;
        byte[] raw = new byte[packet.width * packet.height * bytesPerPixel];
        int destination = 0;
        for (int y = minY; y <= maxY; ++y) {
            int source = (y * 240 + minX) * bytesPerPixel;
            int count = packet.width * bytesPerPixel;
            System.arraycopy(full, source, raw, destination, count);
            destination += count;
        }
        ByteArrayOutputStream encoded = new ByteArrayOutputStream(raw.length);
        int pixels = packet.width * packet.height;
        int pixel = 0;
        while (pixel < pixels) {
            int run = 1;
            int offset = pixel * bytesPerPixel;
            while (pixel + run < pixels && run < 255) {
                int candidate = (pixel + run) * bytesPerPixel;
                boolean same = true;
                for (int byteIndex = 0; byteIndex < bytesPerPixel; ++byteIndex) {
                    if (raw[offset + byteIndex] != raw[candidate + byteIndex]) {
                        same = false; break;
                    }
                }
                if (!same) break;
                ++run;
            }
            encoded.write(run);
            encoded.write(raw, offset, bytesPerPixel);
            pixel += run;
        }
        byte[] rle = encoded.toByteArray();
        byte[] delta = null;
        if (gifOptimized && previous != null && previous.length == full.length) {
            ByteArrayOutputStream sparse = new ByteArrayOutputStream(raw.length);
            int local = 0;
            while (local < pixels) {
                int skip = 0;
                while (local < pixels) {
                    int global = (minY + local / packet.width) * 240 +
                            minX + local % packet.width;
                    if (full[global] != previous[global] || skip == 65535) break;
                    ++skip;
                    ++local;
                }
                if (skip == 65535 && local < pixels) {
                    sparse.write(0xFF); sparse.write(0xFF); sparse.write(0);
                    continue;
                }
                int runStart = local;
                int run = 0;
                while (local < pixels && run < 255) {
                    int global = (minY + local / packet.width) * 240 +
                            minX + local % packet.width;
                    if (full[global] == previous[global]) break;
                    ++run;
                    ++local;
                }
                if (run == 0) continue;
                sparse.write(skip & 0xFF);
                sparse.write((skip >> 8) & 0xFF);
                sparse.write(run);
                for (int index = 0; index < run; ++index) {
                    int point = runStart + index;
                    int global = (minY + point / packet.width) * 240 +
                            minX + point % packet.width;
                    sparse.write(full[global]);
                }
            }
            delta = sparse.toByteArray();
        }
        if (delta != null && delta.length >= 4 && delta.length < raw.length &&
                delta.length < rle.length) {
            packet.data = delta;
            packet.encoding = "delta332";
        } else if (rle.length < raw.length) {
            packet.data = rle;
            packet.encoding = gifOptimized ? "rle332" : "rle565";
        } else {
            packet.data = raw;
            packet.encoding = gifOptimized ? "rgb332" : "raw565";
        }
        return packet;
    }

    private void sendSelectedFrame() {
        if (selectedPreview == null) { toast("请先选择媒体"); return; }
        int transport = selectedTransport();
        Bitmap frame = selectedPreview;
        String endpoint = baseUrl();
        status("正在手机端压缩图片…", true);
        worker.execute(() -> {
            MediaPacket packet = encodeMediaPacket(frame, null, false);
            if (transport == 1) runOnUiThread(() -> startBleMedia(packet, 100, null));
            else {
                try {
                    String response = httpBlocking("POST", endpoint + packet.httpPath(100),
                            packet.data, "application/octet-stream", 30000);
                    runOnUiThread(() -> status("图片已显示，未写 Flash\n" +
                            packet.description() + "\n" + response, true));
                } catch (Exception error) {
                    runOnUiThread(() -> status("图片上传失败：" + error.getMessage(), false));
                }
            }
        });
    }
    private void saveWallpaper() {
        if (selectedPreview == null) { toast("请先选择媒体"); return; }
        int transport = selectedTransport();
        Bitmap frame = selectedPreview;
        String endpoint = baseUrl();
        status("正在手机端生成高质量壁纸…", true);
        worker.execute(() -> {
            byte[] data = bitmapToRgb565(frame);
            if (transport == 1) runOnUiThread(() ->
                    startBleFile("WALLPAPER", data, 0,
                            () -> status("壁纸已保存，并作为设备界面底层", true)));
            else {
                try {
                    String response = httpBlocking("POST", endpoint + "/api/wallpaper",
                            data, "application/octet-stream", 45000);
                    runOnUiThread(() -> status("壁纸已保存，并作为设备界面底层\n" +
                            response, true));
                } catch (Exception error) {
                    runOnUiThread(() -> status("壁纸上传失败：" + error.getMessage(), false));
                }
            }
        });
    }
    private void uploadBytes(String path, byte[] data, String message) {
        showProgress(0);
        String endpoint = baseUrl() + path;
        worker.execute(() -> {
            try {
                String response = httpBlocking("POST", endpoint, data,
                        "application/octet-stream", 45000);
                runOnUiThread(() -> { showProgress(100); status(message + "\n" + response, true); });
            } catch (Exception error) {
                runOnUiThread(() -> status("上传失败：" + error.getMessage(), false));
            }
        });
    }
    private void startGifStream() {
        if (selectedMovie == null || selectedCropRect == null) {
            toast("请选择 GIF 并先确认裁剪"); return;
        }
        final int transport = selectedTransport();
        final String endpoint = baseUrl();
        final String address = bluetoothGatt != null ? bluetoothGatt.getDevice().getAddress()
                : preferences.getString("ble_address", "");
        if (transport == 1 && address.isEmpty()) {
            status("请先连接一次 BLE，让后台播放器记住设备", false); return;
        }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(
                Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},
                    REQUEST_NOTIFICATION_PERMISSION);
        }
        gifStreaming = true;
        lastGifComparisonFrame = null;
        status("正在一次性预处理 GIF；完成后退出 APK 仍会继续播放…", true);
        showProgress(0);
        Intent preparing = new Intent(this, GifPlaybackService.class)
                .setAction(GifPlaybackService.ACTION_PREPARE);
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(preparing);
        else startService(preparing);
        final Movie movie = selectedMovie;
        worker.execute(() -> prepareGifClip(movie, transport, endpoint, address));
    }

    private void prepareGifClip(Movie movie, int transport, String endpoint, String address) {
        ArrayList<MediaPacket> loopFrames = new ArrayList<>();
        try {
            int duration = Math.max(1000, movie.duration());
            int baseInterval = transport == 1 ? 180 : 90;
            int maximumFrames = transport == 1 ? 120 : 240;
            int interval = Math.max(baseInterval,
                    ((duration + maximumFrames * 20 - 1) / (maximumFrames * 20)) * 20);
            int sampledFrames = Math.max(2, (duration + interval - 1) / interval);
            Bitmap first = renderCroppedMovieFrame(movie, 0);
            MediaPacket bootstrap = encodeMediaPacket(first, null, true);
            byte[] firstQuantized = bootstrap.comparisonFrame;
            byte[] previous = firstQuantized;
            bootstrap.comparisonFrame = null;
            first.recycle();
            long payloadBytes = bootstrap.data.length;
            for (int frameIndex = 1; frameIndex < sampledFrames; ++frameIndex) {
                if (!gifStreaming) throw new IOException("用户已取消预处理");
                Bitmap bitmap = renderCroppedMovieFrame(movie,
                        Math.min(duration - 1, frameIndex * interval));
                MediaPacket packet = encodeMediaPacket(bitmap, previous, true);
                previous = packet.comparisonFrame;
                packet.comparisonFrame = null;
                bitmap.recycle();
                payloadBytes += packet.data.length;
                loopFrames.add(packet);
                final int progress = frameIndex * 90 / sampledFrames;
                runOnUiThread(() -> showProgress(progress));
            }
            Bitmap loopBitmap = renderCroppedMovieFrame(movie, 0);
            MediaPacket loopToFirst = encodeMediaPacket(loopBitmap, previous, true);
            loopToFirst.comparisonFrame = null;
            loopBitmap.recycle();
            payloadBytes += loopToFirst.data.length;
            loopFrames.add(loopToFirst);

            File directory = new File(getFilesDir(), "gif-clips");
            if (!directory.exists() && !directory.mkdirs())
                throw new IOException("无法创建 GIF 播放缓存");
            File clip = new File(directory, "active.lcg");
            try (DataOutputStream output = new DataOutputStream(new BufferedOutputStream(
                    new FileOutputStream(clip)))) {
                output.writeInt(GifPlaybackService.CLIP_MAGIC);
                output.writeInt(GifPlaybackService.CLIP_VERSION);
                output.writeInt(interval);
                output.writeInt(loopFrames.size());
                writeClipFrame(output, bootstrap);
                for (MediaPacket packet : loopFrames) writeClipFrame(output, packet);
            }
            final long bytes = payloadBytes;
            final int frames = sampledFrames;
            final int frameInterval = interval;
            runOnUiThread(() -> startGifService(clip, transport, endpoint, address,
                    frames, frameInterval, bytes));
        } catch (Exception error) {
            gifStreaming = false;
            runOnUiThread(() -> {
                Intent stop = new Intent(this, GifPlaybackService.class)
                        .setAction(GifPlaybackService.ACTION_STOP);
                startService(stop);
                status("GIF 预处理失败：" + error.getMessage(), false);
            });
        }
    }

    private static void writeClipFrame(DataOutputStream output, MediaPacket packet)
            throws IOException {
        int encoding = "rgb332".equals(packet.encoding) ? 1 :
                "rle332".equals(packet.encoding) ? 2 :
                        "delta332".equals(packet.encoding) ? 3 : 0;
        output.writeByte(encoding);
        output.writeShort(packet.x);
        output.writeShort(packet.y);
        output.writeShort(packet.width);
        output.writeShort(packet.height);
        output.writeInt(packet.data == null ? 0 : packet.data.length);
        if (packet.data != null) output.write(packet.data);
    }

    private void startGifService(File clip, int transport, String endpoint, String address,
                                 int frames, int interval, long bytes) {
        if (!gifStreaming) return;
        if (transport == 1) releaseActivityBle();
        Intent service = new Intent(this, GifPlaybackService.class)
                .setAction(GifPlaybackService.ACTION_START)
                .putExtra(GifPlaybackService.EXTRA_FILE, clip.getAbsolutePath())
                .putExtra(GifPlaybackService.EXTRA_TRANSPORT, transport)
                .putExtra(GifPlaybackService.EXTRA_ENDPOINT, endpoint)
                .putExtra(GifPlaybackService.EXTRA_BLE_ADDRESS, address)
                .putExtra(GifPlaybackService.EXTRA_SPEED_PERCENT, gifSpeedPercent);
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(service); else startService(service);
        gifStreaming = false;
        String description = String.format(Locale.US,
                "后台 GIF 已启动 · %d 帧缓存 · %.1f fps · %d%% · 每轮 %,d B",
                frames, 1000f / interval * gifSpeedPercent / 100f,
                gifSpeedPercent, bytes);
        if (!isDestroyed()) {
            showProgress(100);
            if (mediaInfo != null)
                mediaInfo.setText(description + "\n退出 APK 后由系统通知继续控制");
            status(description, true);
        }
    }

    private void releaseActivityBle() {
        if (bluetoothGatt != null && hasBlePermissions()) {
            preferences.edit().putString("ble_address",
                    bluetoothGatt.getDevice().getAddress()).apply();
            bluetoothGatt.disconnect();
            bluetoothGatt.close();
        }
        bluetoothGatt = null;
        bleReady = false;
    }
    private void streamGifWifi(Movie movie, String endpoint) {
        int duration = Math.max(1000, movie.duration());
        long started = System.currentTimeMillis();
        while (gifStreaming) {
            long frameStarted = System.currentTimeMillis();
            int time = (int) ((System.currentTimeMillis() - started) % duration);
            Bitmap frame = renderCroppedMovieFrame(movie, time);
            MediaPacket packet = encodeMediaPacket(frame, lastGifComparisonFrame, true);
            lastGifComparisonFrame = packet.comparisonFrame;
            try {
                if (!packet.unchanged) httpBlocking("POST", endpoint + packet.httpPath(125),
                        packet.data, "application/octet-stream", 20000);
                runOnUiThread(() -> {
                    if (mediaPreview != null) mediaPreview.setImageBitmap(frame);
                    if (mediaInfo != null) mediaInfo.setText("GIF Wi‑Fi · " + packet.description());
                });
            } catch (Exception error) {
                gifStreaming = false;
                runOnUiThread(() -> status("GIF 流中断：" + error.getMessage(), false));
            }
            long remaining = 125 - (System.currentTimeMillis() - frameStarted);
            if (remaining > 0) try { Thread.sleep(remaining); }
            catch (InterruptedException ignored) { Thread.currentThread().interrupt(); break; }
        }
    }
    private void streamNextGifFrameBle(int time) {
        if (!gifStreaming || selectedMovie == null) return;
        int duration = Math.max(1000, selectedMovie.duration());
        int nextTime = (time + 350) % duration;
        worker.execute(() -> {
            Bitmap frame = renderCroppedMovieFrame(selectedMovie, time);
            MediaPacket packet = encodeMediaPacket(frame, lastGifComparisonFrame, true);
            lastGifComparisonFrame = packet.comparisonFrame;
            runOnUiThread(() -> {
                if (!gifStreaming) return;
                if (mediaPreview != null) mediaPreview.setImageBitmap(frame);
                if (mediaInfo != null) mediaInfo.setText("GIF BLE · " + packet.description());
                if (packet.unchanged) {
                    mainHandler.postDelayed(() -> streamNextGifFrameBle(nextTime), 80);
                } else {
                    startBleMedia(packet, 350,
                            () -> mainHandler.postDelayed(
                                    () -> streamNextGifFrameBle(nextTime), 40));
                }
            });
        });
    }
    private void stopGifStreamSilently() {
        gifStreaming = false;
        lastGifComparisonFrame = null;
    }
    private void stopGifStream() {
        stopGifStreamSilently();
        Intent stop = new Intent(this, GifPlaybackService.class)
                .setAction(GifPlaybackService.ACTION_STOP);
        startService(stop);
        status("GIF 后台播放已停止", true);
    }
    private void startFirmwareUpdate() {
        if (selectedFirmware == null) { toast("请先选择固件"); return; }
        if (selectedTransport() == 1) startBleOta();
        else uploadBytes("/api/ota", selectedFirmware, "固件校验成功，设备正在重启");
    }

    private void showBleWifiDialog() {
        if (!bleReady) {
            status("请先点击“扫描 BLE”并等待显示 BLE 已就绪", false);
            return;
        }
        LinearLayout form = new LinearLayout(this);
        form.setOrientation(LinearLayout.VERTICAL);
        form.setPadding(dp(20), dp(8), dp(20), 0);
        TextView guide = label("输入家中/实验室路由器的 2.4 GHz Wi‑Fi。手机不会切换网络。",
                13, MUTED, false);
        EditText ssid = input(preferences.getString("wifi_ssid", ""),
                "路由器 SSID（区分大小写）", false);
        EditText password = input(secureStore.get("wifi_password"),
                "Wi‑Fi 密码（开放网络可留空）", true);
        form.addView(guide, matchWrap(0));
        form.addView(ssid, matchWrap(dp(8)));
        form.addView(password, matchWrap(dp(6)));
        new AlertDialog.Builder(this).setTitle("通过蓝牙连接外部 Wi‑Fi")
                .setView(form).setNegativeButton("取消", null)
                .setPositiveButton("保存并连接", (dialog, which) ->
                        configureWifiOverBle(ssid.getText().toString().trim(),
                                password.getText().toString())).show();
    }

    private void configureWifiOverBle(String ssid, String password) {
        if (ssid.isEmpty()) { status("SSID 不能为空，请重新打开配网", false); return; }
        if (ssid.getBytes(StandardCharsets.UTF_8).length > 32 ||
                password.getBytes(StandardCharsets.UTF_8).length > 63) {
            status("SSID 或密码超过 Wi‑Fi 标准长度", false); return;
        }
        preferences.edit().putString("wifi_ssid", ssid).putBoolean("keep_ap", true).apply();
        secureStore.put("wifi_password", password);
        String encodedSsid = Base64.encodeToString(ssid.getBytes(StandardCharsets.UTF_8),
                Base64.NO_WRAP);
        String encodedPassword = Base64.encodeToString(
                password.getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP);
        status("配网信息正在通过 BLE 下发；手机保持当前联网状态…", true);
        writeBleCommand("WIFI:" + encodedSsid + ":" + encodedPassword);
        mainHandler.postDelayed(() -> writeBleCommand("STATUS", true), 1800);
        mainHandler.postDelayed(() -> writeBleCommand("STATUS", true), 4500);
        mainHandler.postDelayed(() -> writeBleCommand("STATUS", false), 8500);
    }

    private void restoreRecoveryAp() {
        if (!bleReady) {
            status("恢复热点需要 BLE 连接；请先扫描并连接设备", false); return;
        }
        status("正在通过 BLE 恢复设备热点…", true);
        writeBleCommand("AP:ON");
        mainHandler.postDelayed(() -> writeBleCommand("STATUS", false), 1200);
    }

    private void openUrl(String url) {
        try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))); }
        catch (Exception error) { status("无法打开链接：" + error.getMessage(), false); }
    }

    private void startScreenMonitor() {
        screenMonitorActive = true;
        if (screenMonitorState != null) {
            screenMonitorState.setText("● 正在建立实时镜像…");
            screenMonitorState.setTextColor(GREEN);
        }
        mainHandler.removeCallbacks(screenMonitorRunnable);
        mainHandler.post(screenMonitorRunnable);
    }

    private void stopScreenMonitorSilently() {
        screenMonitorActive = false;
        mainHandler.removeCallbacks(screenMonitorRunnable);
    }

    private void stopScreenMonitor() {
        stopScreenMonitorSilently();
        if (screenMonitorState != null) {
            screenMonitorState.setText("● 实时监看已停止");
            screenMonitorState.setTextColor(MUTED);
        }
        status("屏幕实时镜像已停止", true);
    }

    private void saveNetworkSettings() {
        preferences.edit().putString("wifi_ssid", wifiSsid.getText().toString().trim())
                .putString("mqtt_uri", mqttUri.getText().toString().trim())
                .putString("mqtt_user", mqttUser.getText().toString().trim())
                .putString("mqtt_topic", mqttTopic.getText().toString().trim())
                .putString("brightness", brightnessInput.getText().toString().trim())
                .putBoolean("keep_ap", keepRecoveryAp.isChecked())
                .putBoolean("remote", remoteEnabled.isChecked()).apply();
        secureStore.put("mqtt_password", mqttPassword.getText().toString());
        secureStore.put("wifi_password", wifiPassword.getText().toString());
        try {
            int brightness = Integer.parseInt(brightnessInput.getText().toString().trim());
            if (selectedTransport() == 1) {
                configureWifiOverBle(wifiSsid.getText().toString().trim(),
                        wifiPassword.getText().toString());
                status("BLE 已下发 Wi‑Fi；MQTT 等高级项将在局域网连接后同步", true);
                return;
            }
            JSONObject config = new JSONObject()
                    .put("ssid", wifiSsid.getText().toString())
                    .put("password", wifiPassword.getText().toString())
                    .put("mqttUri", mqttUri.getText().toString())
                    .put("mqttUser", mqttUser.getText().toString())
                    .put("mqttPassword", mqttPassword.getText().toString())
                    .put("mqttTopic", mqttTopic.getText().toString())
                    .put("keepAp", keepRecoveryAp.isChecked())
                    .put("remote", remoteEnabled.isChecked())
                    .put("brightness", Math.max(0, Math.min(100, brightness)))
                    .put("locale", "zh-CN");
            http("POST", "/api/network", config.toString().getBytes(StandardCharsets.UTF_8),
                    "application/json",
                    result -> {
                        status("网络设置已保存，正在等待设备获得局域网 IP…", true);
                        mainHandler.postDelayed(this::fetchStatus, 1800);
                        mainHandler.postDelayed(this::fetchStatus, 4200);
                        mainHandler.postDelayed(this::fetchStatus, 8000);
                    });
        } catch (Exception error) { status("配置失败：" + error.getMessage(), false); }
    }
    private void saveAiSettings() {
        preferences.edit().putString("ai_endpoint", aiEndpoint.getText().toString().trim())
                .putString("ai_model", aiModel.getText().toString().trim()).apply();
        secureStore.put("ai_key", aiKey.getText().toString().trim());
        status("AI 设置已加密保存", true);
    }
    private void generateProtocol() {
        String question = aiQuestion.getText().toString().trim();
        if (question.isEmpty()) { toast("请输入实验问题"); return; }
        saveAiSettings();
        String endpoint = aiEndpoint.getText().toString().trim(),
                key = aiKey.getText().toString().trim(),
                model = aiModel.getText().toString().trim();
        if (endpoint.isEmpty() || key.isEmpty() || model.isEmpty()) {
            status("请完整填写 API 信息", false); return;
        }
        status("AI 正在生成实验协议…", true);
        worker.execute(() -> {
            try {
                JSONObject system = new JSONObject().put("role", "system").put("content",
                        "你是 LabCapsule 实验设计助手。只输出严格 JSON，字段为 name、sample_rate_hz、duration_seconds、groups、analysis。设备当前主要支持运动与振动实验。");
                JSONObject user = new JSONObject().put("role", "user").put("content", question);
                JSONObject request = new JSONObject().put("model", model).put("temperature", .2)
                        .put("messages", new JSONArray().put(system).put(user));
                HttpURLConnection connection = (HttpURLConnection) new URL(endpoint).openConnection();
                connection.setRequestMethod("POST");
                connection.setConnectTimeout(10000);
                connection.setReadTimeout(60000);
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/json");
                connection.setRequestProperty("Authorization", "Bearer " + key);
                byte[] body = request.toString().getBytes(StandardCharsets.UTF_8);
                connection.setFixedLengthStreamingMode(body.length);
                try (OutputStream output = connection.getOutputStream()) { output.write(body); }
                int code = connection.getResponseCode();
                InputStream stream = code >= 200 && code < 300 ? connection.getInputStream()
                        : connection.getErrorStream();
                String raw = new String(readAll(stream), StandardCharsets.UTF_8);
                connection.disconnect();
                if (code < 200 || code >= 300) throw new Exception(raw);
                String protocol = normalizeProtocol(new JSONObject(raw).getJSONArray("choices")
                        .getJSONObject(0).getJSONObject("message").getString("content"));
                runOnUiThread(() -> {
                    currentProtocol = protocol;
                    aiResult.setText(protocol);
                    aiResult.setTextColor(INK);
                    status("实验协议生成完成", true);
                });
            } catch (Exception error) {
                String fallback = fallbackProtocol(question);
                runOnUiThread(() -> {
                    currentProtocol = fallback;
                    aiResult.setText(fallback);
                    aiResult.setTextColor(INK);
                    status("AI 请求失败，已使用本地安全模板：" + error.getMessage(), false);
                });
            }
        });
    }

    private static String normalizeProtocol(String content) throws Exception {
        String value = content.trim();
        if (value.startsWith("```")) {
            int firstLine = value.indexOf('\n');
            int closing = value.lastIndexOf("```");
            if (firstLine >= 0 && closing > firstLine) value = value.substring(firstLine + 1, closing).trim();
        }
        JSONObject protocol = new JSONObject(value);
        int rate = protocol.getInt("sample_rate_hz");
        int duration = protocol.getInt("duration_seconds");
        if (rate < 10 || rate > 500 || duration < 1 || duration > 3600)
            throw new Exception("协议采样率或时长超出设备安全范围");
        protocol.getString("name");
        protocol.getJSONArray("groups");
        protocol.getJSONArray("analysis");
        return protocol.toString(2);
    }

    private static String fallbackProtocol(String question) {
        try {
            return new JSONObject().put("name", question.isEmpty() ? "运动振动对照实验" : question)
                    .put("sample_rate_hz", 200).put("duration_seconds", 20)
                    .put("groups", new JSONArray().put("对照组").put("实验组"))
                    .put("analysis", new JSONArray().put("RMS").put("Peak").put("FFT"))
                    .put("source", "local_fallback").toString(2);
        } catch (Exception ignored) { return "{}"; }
    }

    private void sendCurrentProtocol() {
        if (currentProtocol == null || currentProtocol.trim().isEmpty()) {
            toast("请先生成实验协议"); return;
        }
        executeProtocol(currentProtocol);
    }

    private void checkForUpdates(boolean silent) {
        if (!silent) status("正在检查 GitHub Releases…", true);
        worker.execute(() -> {
            try {
                String raw = httpBlocking("GET", "https://api.github.com/repos/" +
                        REPOSITORY + "/releases/latest", null, null, 20000);
                JSONObject release = new JSONObject(raw);
                String tag = release.optString("tag_name", "未知");
                latestApkUrl = latestFirmwareUrl = null;
                JSONArray assets = release.optJSONArray("assets");
                if (assets != null) for (int i = 0; i < assets.length(); ++i) {
                    JSONObject asset = assets.getJSONObject(i);
                    String name = asset.optString("name").toLowerCase(Locale.ROOT);
                    if (name.endsWith(".apk")) latestApkUrl = asset.optString("browser_download_url");
                    if (name.endsWith(".bin") && name.contains("ota"))
                        latestFirmwareUrl = asset.optString("browser_download_url");
                }
                runOnUiThread(() -> {
                    if (updateInfo != null) updateInfo.setText("当前 " + APP_VERSION + " · 最新 " + tag);
                    if (!silent) status("版本检查完成：" + tag, true);
                });
            } catch (Exception error) {
                if (!silent) runOnUiThread(() -> status("更新检查失败：" + error.getMessage(), false));
            }
        });
    }
    private void downloadLatestApk() {
        if (latestApkUrl == null) { checkForUpdates(false); toast("检查完成后再次点击下载"); return; }
        DownloadManager manager = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
        DownloadManager.Request request = new DownloadManager.Request(Uri.parse(latestApkUrl));
        request.setTitle("LabCapsule APK 更新");
        request.setDescription("下载完成后点击通知安装");
        request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
        request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS,
                "LabCapsule-latest.apk");
        manager.enqueue(request);
        status("APK 已加入系统下载队列", true);
    }
    private void downloadLatestFirmware() {
        if (latestFirmwareUrl == null) {
            checkForUpdates(false); toast("检查完成后再次点击下载"); return;
        }
        status("正在下载最新 OTA 固件…", true);
        worker.execute(() -> {
            try (InputStream input = new URL(latestFirmwareUrl).openStream()) {
                selectedFirmware = readAll(input);
                runOnUiThread(() -> {
                    if (firmwareInfo != null) firmwareInfo.setText("GitHub 最新固件 · " +
                            selectedFirmware.length + " bytes");
                    status("固件下载完成，可开始 OTA", true);
                });
            } catch (Exception error) {
                runOnUiThread(() -> status("固件下载失败：" + error.getMessage(), false));
            }
        });
    }
    private static String enc(String value) throws Exception {
        return URLEncoder.encode(value, "UTF-8");
    }

    private boolean hasBlePermissions() {
        if (Build.VERSION.SDK_INT >= 31) return checkSelfPermission(
                Manifest.permission.BLUETOOTH_SCAN) == PackageManager.PERMISSION_GRANTED &&
                checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) ==
                        PackageManager.PERMISSION_GRANTED;
        return checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) ==
                PackageManager.PERMISSION_GRANTED;
    }
    private void startBleScan() {
        if (!hasBlePermissions()) {
            scanAfterPermission = true;
            if (Build.VERSION.SDK_INT >= 31) requestPermissions(new String[]{
                    Manifest.permission.BLUETOOTH_SCAN,
                    Manifest.permission.BLUETOOTH_CONNECT}, REQUEST_BLE_PERMISSIONS);
            else requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION},
                    REQUEST_BLE_PERMISSIONS);
            return;
        }
        if (bluetoothAdapter == null || !bluetoothAdapter.isEnabled()) {
            status("请先开启蓝牙", false); return;
        }
        bleScanner = bluetoothAdapter.getBluetoothLeScanner();
        if (bleScanner == null) { status("BLE 扫描器不可用", false); return; }
        status("正在扫描 LabCapsule…", true);
        bleScanner.startScan(scanCallback);
        mainHandler.postDelayed(() -> {
            if (bleScanner != null && hasBlePermissions()) {
                bleScanner.stopScan(scanCallback);
                bleScanner = null;
                if (!bleReady) status("未发现 LabCapsule", false);
            }
        }, 10000);
    }
    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions,
                                                      int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode == REQUEST_BLE_PERMISSIONS && scanAfterPermission) {
            scanAfterPermission = false;
            if (hasBlePermissions()) startBleScan(); else status("未获得 BLE 权限", false);
        }
    }
    private final ScanCallback scanCallback = new ScanCallback() {
        @Override public void onScanResult(int callbackType, ScanResult result) {
            if (!hasBlePermissions()) return;
            BluetoothDevice device = result.getDevice();
            String name = result.getScanRecord() == null ? null
                    : result.getScanRecord().getDeviceName();
            if (name == null) name = device.getName();
            if (name == null || !name.startsWith("LabCapsule")) return;
            if (bleScanner != null) bleScanner.stopScan(this);
            bleScanner = null;
            preferences.edit().putString("ble_address", device.getAddress()).apply();
            status("正在连接 " + name + "…", true);
            bluetoothGatt = device.connectGatt(MainActivity.this, false, gattCallback,
                    BluetoothDevice.TRANSPORT_LE);
        }
        @Override public void onScanFailed(int code) {
            runOnUiThread(() -> status("BLE 扫描失败：" + code, false));
        }
    };
    private final BluetoothGattCallback gattCallback = new BluetoothGattCallback() {
        @Override public void onConnectionStateChange(BluetoothGatt gatt, int code, int state) {
            if (state == BluetoothProfile.STATE_CONNECTED && code == BluetoothGatt.GATT_SUCCESS) {
                runOnUiThread(() -> status("BLE 已连接，正在发现服务…", true));
                if (hasBlePermissions()) gatt.discoverServices();
            } else if (state == BluetoothProfile.STATE_DISCONNECTED) {
                bleReady = false;
                closeLiveCapture();
                if ("offline_open".equals(bleTransferPhase) ||
                        "offline_read".equals(bleTransferPhase)) {
                    bleTransferPhase = "idle";
                    closeOfflineSync(true);
                }
                runOnUiThread(() -> status("BLE 已断开", false));
            }
        }
        @Override public void onServicesDiscovered(BluetoothGatt gatt, int code) {
            BluetoothGattService service = code == BluetoothGatt.GATT_SUCCESS
                    ? gatt.getService(SERVICE_UUID) : null;
            if (service == null) {
                runOnUiThread(() -> status("LabCapsule BLE 服务不可用", false)); return;
            }
            commandCharacteristic = service.getCharacteristic(COMMAND_UUID);
            statusCharacteristic = service.getCharacteristic(STATUS_UUID);
            otaControlCharacteristic = service.getCharacteristic(OTA_CONTROL_UUID);
            otaDataCharacteristic = service.getCharacteristic(OTA_DATA_UUID);
            fileControlCharacteristic = service.getCharacteristic(FILE_CONTROL_UUID);
            fileDataCharacteristic = service.getCharacteristic(FILE_DATA_UUID);
            experimentDataCharacteristic = service.getCharacteristic(EXPERIMENT_DATA_UUID);
            bleReady = commandCharacteristic != null && statusCharacteristic != null &&
                    otaControlCharacteristic != null && otaDataCharacteristic != null &&
                    fileControlCharacteristic != null && fileDataCharacteristic != null;
            boolean mtuPending = hasBlePermissions() && gatt.requestMtu(517);
            if (!mtuPending) enableExperimentNotifications(gatt);
            runOnUiThread(() -> {
                if (bleReady) {
                    preferences.edit().putInt("transport", 1).apply();
                    if (transportSpinner != null) transportSpinner.setSelection(1);
                }
                status(bleReady ? "BLE 控制、实时实验、离线同步与媒体通道已就绪"
                        : "BLE 特征不完整", bleReady);
            });
        }
        @Override public void onMtuChanged(BluetoothGatt gatt, int mtu, int code) {
            if (code == BluetoothGatt.GATT_SUCCESS) bleMtu = mtu;
            enableExperimentNotifications(gatt);
        }
        @Override @SuppressWarnings("deprecation") public void onCharacteristicRead(
                BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, int code) {
            handleBleRead(characteristic, characteristic.getValue(), code);
        }
        @Override public void onCharacteristicRead(BluetoothGatt gatt,
                BluetoothGattCharacteristic characteristic, byte[] value, int code) {
            handleBleRead(characteristic, value, code);
        }
        @Override @SuppressWarnings("deprecation") public void onCharacteristicChanged(
                BluetoothGatt gatt, BluetoothGattCharacteristic characteristic) {
            handleExperimentNotification(characteristic, characteristic.getValue());
        }
        @Override public void onCharacteristicChanged(BluetoothGatt gatt,
                BluetoothGattCharacteristic characteristic, byte[] value) {
            handleExperimentNotification(characteristic, value);
        }
        @Override public void onCharacteristicWrite(BluetoothGatt gatt,
                BluetoothGattCharacteristic characteristic, int code) {
            handleBleWrite(characteristic, code);
        }
    };
    private void handleBleRead(BluetoothGattCharacteristic characteristic, byte[] value,
                               int code) {
        if (characteristic != null && EXPERIMENT_DATA_UUID.equals(characteristic.getUuid()) &&
                "offline_read".equals(bleTransferPhase)) {
            handleOfflineBleChunk(value, code);
            return;
        }
        final boolean quiet = blePendingQuiet;
        blePendingQuiet = false;
        blePendingCommand = "";
        runOnUiThread(() -> {
            if (code != BluetoothGatt.GATT_SUCCESS || value == null) {
                if (!quiet) status("BLE 读取失败：" + code, false);
                return;
            }
            String payload = new String(value, StandardCharsets.UTF_8);
            try {
                JSONObject root = new JSONObject(payload);
                if ("hardware".equals(root.optString("type"))) {
                    handleHardwarePayload(root, root.optString("operationMode", "experiment"));
                } else if ("sensors".equals(root.optString("type"))) {
                    handleSensorPayload(payload);
                } else if ("offline".equals(root.optString("type"))) {
                    handleOfflinePayload(root);
                } else if (root.has("network") || "status".equals(root.optString("type"))) {
                    handleStatusPayload(payload, quiet);
                } else if (!quiet) {
                    status("BLE 在线\n" + payload, true);
                }
            } catch (Exception error) {
                if (!quiet) status("BLE 回包无法解析：" + payload, false);
            }
        });
    }

    @SuppressWarnings("deprecation")
    private void enableExperimentNotifications(BluetoothGatt gatt) {
        if (gatt == null || experimentDataCharacteristic == null || !hasBlePermissions()) return;
        if (!gatt.setCharacteristicNotification(experimentDataCharacteristic, true)) return;
        BluetoothGattDescriptor descriptor = experimentDataCharacteristic.getDescriptor(
                UUID.fromString("00002902-0000-1000-8000-00805f9b34fb"));
        if (descriptor == null) return;
        if (Build.VERSION.SDK_INT >= 33) {
            gatt.writeDescriptor(descriptor, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
        } else {
            descriptor.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
            gatt.writeDescriptor(descriptor);
        }
    }

    private void handleExperimentNotification(BluetoothGattCharacteristic characteristic,
                                              byte[] value) {
        if (characteristic == null || !EXPERIMENT_DATA_UUID.equals(characteristic.getUuid()) ||
                value == null || value.length != 17 || value[0] != 0x10) return;
        long elapsed = unsignedInt(littleInt(value, 1));
        double[] axes = new double[6];
        for (int axis = 0; axis < 6; ++axis) {
            short packed = (short)littleShort(value, 5 + axis * 2);
            axes[axis] = packed / (axis < 3 ? 4096.0 : 16.0);
        }
        synchronized (this) {
            try {
                if (liveCaptureOutput == null || elapsed <= lastLiveElapsed) {
                    if (liveCaptureOutput != null) liveCaptureOutput.close();
                    File directory = new File(getFilesDir(), "live-experiments");
                    if (!directory.exists()) directory.mkdirs();
                    File target = new File(directory, "ble-" + System.currentTimeMillis() + ".csv");
                    liveCaptureOutput = new BufferedOutputStream(new FileOutputStream(target));
                    liveCaptureOutput.write(
                            "timestamp_us,ax,ay,az,gx,gy,gz\n".getBytes(StandardCharsets.UTF_8));
                    preferences.edit().putString("last_live_file", target.getAbsolutePath()).apply();
                    liveCaptureSamples = 0;
                }
                String line = String.format(Locale.US,
                        "%d,%.5f,%.5f,%.5f,%.5f,%.5f,%.5f\n", elapsed,
                        axes[0], axes[1], axes[2], axes[3], axes[4], axes[5]);
                liveCaptureOutput.write(line.getBytes(StandardCharsets.UTF_8));
                lastLiveElapsed = elapsed;
                ++liveCaptureSamples;
                mainHandler.removeCallbacks(liveCaptureIdleCloseRunnable);
                mainHandler.postDelayed(liveCaptureIdleCloseRunnable, 1500);
                if (liveCaptureSamples % 50 == 0) {
                    liveCaptureOutput.flush();
                    preferences.edit().putInt("last_live_samples", liveCaptureSamples).apply();
                    runOnUiThread(() -> {
                        if (offlineStoreState != null)
                            offlineStoreState.setText("● BLE 实时接收中 · " +
                                    liveCaptureSamples + " 个样本\n已直接保存到手机");
                    });
                }
            } catch (Exception error) {
                try { if (liveCaptureOutput != null) liveCaptureOutput.close(); }
                catch (Exception ignored) { }
                liveCaptureOutput = null;
            }
        }
    }

    private synchronized void closeLiveCapture() {
        mainHandler.removeCallbacks(liveCaptureIdleCloseRunnable);
        try { if (liveCaptureOutput != null) liveCaptureOutput.close(); }
        catch (Exception ignored) { }
        liveCaptureOutput = null;
        lastLiveElapsed = -1;
    }

    private void finishLiveCaptureAfterIdle() {
        final int completedSamples;
        synchronized (this) {
            if (liveCaptureOutput == null) return;
            completedSamples = liveCaptureSamples;
            closeLiveCapture();
        }
        preferences.edit().putInt("last_live_samples", completedSamples).apply();
        if (offlineStoreState != null) {
            offlineStoreState.setText("● BLE 实时实验已保存 · " + completedSamples +
                    " 个样本\n可在数据页导入或分享");
            offlineStoreState.setTextColor(GREEN);
        }
    }

    private void handleOfflineBleChunk(byte[] value, int code) {
        if (code != BluetoothGatt.GATT_SUCCESS || value == null || value.length < 1) {
            bleTransferPhase = "idle";
            closeOfflineSync(true);
            runOnUiThread(() -> status("BLE 离线数据读取失败：" + code, false));
            return;
        }
        try {
            int type = value[0] & 0xFF;
            if (type == 0x20) {
                if (value.length > 1) {
                    offlineSyncOutput.write(value, 1, value.length - 1);
                    offlineSyncBytes += value.length - 1;
                }
                if (bluetoothGatt == null || experimentDataCharacteristic == null ||
                        !hasBlePermissions() ||
                        !bluetoothGatt.readCharacteristic(experimentDataCharacteristic))
                    throw new IOException("无法继续读取 BLE 数据");
            } else if (type == 0x21) {
                offlineSyncOutput.close();
                offlineSyncOutput = null;
                bleTransferPhase = "idle";
                finishOfflineSync();
            } else {
                throw new IOException("未知离线数据帧 " + type);
            }
        } catch (Exception error) {
            bleTransferPhase = "idle";
            closeOfflineSync(true);
            runOnUiThread(() -> status("BLE 离线同步中断：" + error.getMessage(), false));
        }
    }
    private void writeBleCommand(String command) {
        writeBleCommand(command, false);
    }
    private void writeBleCommand(String command, boolean quiet) {
        if (!bleReady || !"idle".equals(bleTransferPhase)) {
            if (!quiet) status("BLE 未连接或正在传输", false);
            return;
        }
        blePendingQuiet = quiet;
        blePendingCommand = command;
        String wireCommand = command.startsWith("WIFI:")
                ? command : command.toUpperCase(Locale.ROOT);
        if (!writeCharacteristic(commandCharacteristic,
                wireCommand.getBytes(StandardCharsets.UTF_8)) && !quiet)
            status("BLE 指令发送失败", false);
    }
    private boolean writeCharacteristic(BluetoothGattCharacteristic characteristic,
                                        byte[] value) {
        if (bluetoothGatt == null || characteristic == null || !hasBlePermissions()) return false;
        if (Build.VERSION.SDK_INT >= 33) return bluetoothGatt.writeCharacteristic(characteristic,
                value, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) == 0;
        characteristic.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
        characteristic.setValue(value);
        return bluetoothGatt.writeCharacteristic(characteristic);
    }
    private void startBleOta() {
        if (!bleReady) { status("请先连接 BLE", false); return; }
        bleTransferData = selectedFirmware;
        bleTransferOffset = 0;
        bleTransferPhase = "ota_begin";
        bleTransferKind = "OTA";
        showProgress(0);
        if (!writeCharacteristic(otaControlCharacteristic,
                ("BEGIN:" + selectedFirmware.length).getBytes(StandardCharsets.UTF_8))) {
            bleTransferPhase = "idle";
            status("无法启动 BLE OTA", false);
        }
    }
    private void startBleFile(String kind, byte[] data, int duration,
                              Runnable completion) {
        startBleFile(kind, data, duration, "raw565", 0, 0, 240, 320, completion);
    }
    private void startBleMedia(MediaPacket packet, int duration, Runnable completion) {
        startBleFile("FRAME", packet.data, duration, packet.encoding, packet.x, packet.y,
                packet.width, packet.height, completion);
    }
    private void startBleFile(String kind, byte[] data, int duration, String encoding,
                              int x, int y, int width, int height, Runnable completion) {
        if (!bleReady || !"idle".equals(bleTransferPhase)) {
            status("请先连接 BLE，或等待当前传输结束", false); return;
        }
        CRC32 crc = new CRC32();
        crc.update(data);
        bleTransferData = data;
        bleTransferOffset = 0;
        bleTransferKind = kind;
        bleTransferCompletion = completion;
        bleTransferPhase = "file_begin";
        showProgress(0);
        String begin = String.format(Locale.US,
                "BEGIN:%s:%d:%d:%08X:%s:%d:%d:%d:%d", kind, data.length,
                duration, crc.getValue(), encoding, x, y, width, height);
        if (!writeCharacteristic(fileControlCharacteristic,
                begin.getBytes(StandardCharsets.UTF_8))) {
            bleTransferPhase = "idle";
            status("无法启动 BLE 媒体传输", false);
        }
    }
    private void handleBleWrite(BluetoothGattCharacteristic characteristic, int code) {
        if (code != BluetoothGatt.GATT_SUCCESS) {
            bleTransferPhase = "idle";
            gifStreaming = false;
            runOnUiThread(() -> status("BLE 写入失败：" + code, false));
            return;
        }
        UUID uuid = characteristic.getUuid();
        if ("ota_begin".equals(bleTransferPhase) && uuid.equals(OTA_CONTROL_UUID)) {
            bleTransferPhase = "ota_data"; writeNextBleChunk(otaDataCharacteristic);
        } else if ("ota_data".equals(bleTransferPhase) && uuid.equals(OTA_DATA_UUID)) {
            advanceBleTransfer();
            if (bleTransferOffset >= bleTransferData.length) {
                bleTransferPhase = "ota_end";
                writeCharacteristic(otaControlCharacteristic, "END".getBytes(StandardCharsets.UTF_8));
            } else writeNextBleChunk(otaDataCharacteristic);
        } else if ("ota_end".equals(bleTransferPhase) && uuid.equals(OTA_CONTROL_UUID)) {
            bleTransferPhase = "idle";
            runOnUiThread(() -> { showProgress(100); status("BLE OTA 完成，设备正在重启", true); });
        } else if ("file_begin".equals(bleTransferPhase) && uuid.equals(FILE_CONTROL_UUID)) {
            bleTransferPhase = "file_data"; writeNextBleChunk(fileDataCharacteristic);
        } else if ("file_data".equals(bleTransferPhase) && uuid.equals(FILE_DATA_UUID)) {
            advanceBleTransfer();
            if (bleTransferOffset >= bleTransferData.length) {
                bleTransferPhase = "file_end";
                writeCharacteristic(fileControlCharacteristic, "END".getBytes(StandardCharsets.UTF_8));
            } else writeNextBleChunk(fileDataCharacteristic);
        } else if ("file_end".equals(bleTransferPhase) && uuid.equals(FILE_CONTROL_UUID)) {
            Runnable completion = bleTransferCompletion;
            bleTransferCompletion = null;
            bleTransferPhase = "idle";
            runOnUiThread(() -> {
                showProgress(100);
                status("BLE " + bleTransferKind + " 传输完成", true);
                if (completion != null) completion.run();
            });
        } else if ("offline_open".equals(bleTransferPhase) && uuid.equals(COMMAND_UUID)) {
            bleTransferPhase = "offline_read";
            if (bluetoothGatt == null || experimentDataCharacteristic == null ||
                    !hasBlePermissions() ||
                    !bluetoothGatt.readCharacteristic(experimentDataCharacteristic)) {
                bleTransferPhase = "idle";
                closeOfflineSync(true);
                runOnUiThread(() -> status("无法开始 BLE 离线数据读取", false));
            }
        } else if ("idle".equals(bleTransferPhase) && uuid.equals(COMMAND_UUID)) {
            if (bluetoothGatt == null || statusCharacteristic == null ||
                    !hasBlePermissions() || !bluetoothGatt.readCharacteristic(statusCharacteristic)) {
                final boolean quiet = blePendingQuiet;
                runOnUiThread(() -> {
                    if (!quiet) status("BLE 指令已执行，但无法读取结果", false);
                });
            }
        }
    }
    private void advanceBleTransfer() {
        bleTransferOffset += blePendingLength;
        int progress = bleTransferOffset * 100 / bleTransferData.length;
        runOnUiThread(() -> showProgress(progress));
    }
    private void writeNextBleChunk(BluetoothGattCharacteristic target) {
        int chunk = Math.max(20, Math.min(500, bleMtu - 3));
        blePendingLength = Math.min(chunk, bleTransferData.length - bleTransferOffset);
        byte[] value = new byte[blePendingLength];
        System.arraycopy(bleTransferData, bleTransferOffset, value, 0, blePendingLength);
        if (!writeCharacteristic(target, value)) {
            bleTransferPhase = "idle";
            gifStreaming = false;
            runOnUiThread(() -> status("BLE 传输队列失败", false));
        }
    }

    private static byte[] readAll(InputStream input) throws Exception {
        if (input == null) throw new Exception("输入流为空");
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int count;
        while ((count = input.read(buffer)) >= 0)
            if (count > 0) output.write(buffer, 0, count);
        return output.toByteArray();
    }

    @Override protected void onDestroy() {
        stopScreenMonitorSilently();
        // ACTION_PREPARE has already promoted the process to a foreground service. Let an
        // in-flight one-time GIF preprocessing job finish even when the Activity is swiped
        // away; startGifService() performs the final hand-off. The explicit Stop button sets
        // gifStreaming=false and causes the preparation loop to cancel.
        if (gifStreaming) worker.shutdown(); else worker.shutdownNow();
        if (bleScanner != null && hasBlePermissions()) bleScanner.stopScan(scanCallback);
        if (bluetoothGatt != null && hasBlePermissions()) {
            bluetoothGatt.disconnect();
            bluetoothGatt.close();
        }
        closeLiveCapture();
        closeOfflineSync(false);
        super.onDestroy();
    }

    private final class ArcadeBackdrop extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        ArcadeBackdrop(Context context) { super(context); }
        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            canvas.drawColor(CANVAS);
            paint.setStrokeWidth(dp(1));
            paint.setColor(Color.argb(26, Color.red(MUTED), Color.green(MUTED),
                    Color.blue(MUTED)));
            for (int x = -getHeight(); x < getWidth(); x += dp(34)) {
                canvas.drawLine(x, 0, x + getHeight(), getHeight(), paint);
            }
            paint.setColor(Color.argb(225, Color.red(BLUE), Color.green(BLUE),
                    Color.blue(BLUE)));
            canvas.drawRect(0, dp(24), getWidth() * .42f, dp(31), paint);
            paint.setColor(Color.argb(210, Color.red(SECONDARY), Color.green(SECONDARY),
                    Color.blue(SECONDARY)));
            canvas.drawRect(getWidth() * .72f, getHeight() - dp(120), getWidth(),
                    getHeight() - dp(110), paint);
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(dp(2));
            paint.setColor(Color.argb(70, Color.red(BLUE), Color.green(BLUE),
                    Color.blue(BLUE)));
            canvas.drawRect(dp(9), dp(38), getWidth() - dp(9), getHeight() - dp(10), paint);
            paint.setStyle(Paint.Style.FILL);
        }
    }

    private final class WallpaperPreview extends ImageView {
        private final Paint hudPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private int previewPanelOpacity = 76, previewHudOpacity = 100;
        private String deviceState = "READY", deviceView = "home", deviceMpu = "unknown";
        private boolean deviceBacklight = true;
        WallpaperPreview(Context context) {
            super(context);
            setLayerType(LAYER_TYPE_SOFTWARE, null);
        }
        void setStyle(int preset, int wallpaper, int panel, int hud) {
            previewPanelOpacity = panel;
            previewHudOpacity = hud;
            setImageAlpha(wallpaper * 255 / 100);
            invalidate();
        }
        void setDeviceState(String state, String view, String mpu, boolean backlight) {
            deviceState = state == null ? "READY" : state;
            deviceView = view == null ? "home" : view;
            deviceMpu = mpu == null ? "unknown" : mpu;
            deviceBacklight = backlight;
            invalidate();
        }
        @Override protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
            int width = MeasureSpec.getSize(widthMeasureSpec);
            if (width <= 0) width = dp(240);
            setMeasuredDimension(width, Math.round(width * 320f / 240f));
        }
        private int alphaColor(int color, int percent) {
            return Color.argb(percent * 255 / 100, Color.red(color), Color.green(color),
                    Color.blue(color));
        }
        private void hudText(Canvas canvas, String text, float x, float y, float size,
                             int color, boolean bold) {
            hudPaint.setColor(alphaColor(color, previewHudOpacity));
            hudPaint.setTextSize(size);
            hudPaint.setTypeface(bold ? Typeface.DEFAULT_BOLD : Typeface.MONOSPACE);
            canvas.drawText(text, x, y, hudPaint);
        }
        @Override protected void onDraw(Canvas canvas) {
            canvas.drawColor(CANVAS);
            super.onDraw(canvas);
            float sx = getWidth() / 240f, sy = getHeight() / 320f;
            canvas.save();
            canvas.scale(sx, sy);
            hudPaint.setColor(alphaColor(PANEL, previewPanelOpacity));
            canvas.drawRoundRect(new RectF(0, 0, 240, 116), 0, 0, hudPaint);
            canvas.drawRoundRect(new RectF(12, 128, 228, 190), 8, 8, hudPaint);
            canvas.drawRoundRect(new RectF(12, 202, 228, 302), 8, 8, hudPaint);
            for (int x = 0; x < 240; x += 30) {
                hudPaint.setColor(alphaColor(x % 60 == 0 ? BLUE : SECONDARY,
                        previewHudOpacity));
                canvas.drawRect(x, 0, x + 18, 8, hudPaint);
            }
            hudPaint.setColor(alphaColor(BLUE, previewHudOpacity));
            canvas.drawRoundRect(new RectF(16, 22, 60, 43), 3, 3, hudPaint);
            hudText(canvas, "LC", 25, 38, 14, CANVAS, true);
            hudText(canvas, "LAB CAPSULE", 70, 42, 20, INK, true);
            hudText(canvas, "FIELD UNIT 01", 18, 80, 11, MUTED, false);
            hudPaint.setColor(alphaColor(BLUE, previewHudOpacity));
            canvas.drawRect(18, 104, 222, 107, hudPaint);
            String primary = "home".equals(deviceView) ? deviceState :
                    "settings".equals(deviceView) ? "SETTINGS" :
                    "developer".equals(deviceView) ? "DEVELOPER" :
                    "test".equals(deviceView) ? "COLOR TEST" :
                    "wallpaper".equals(deviceView) ? "WALLPAPER" :
                    "media".equals(deviceView) ? "LIVE MEDIA" : deviceView.toUpperCase(Locale.ROOT);
            hudText(canvas, primary, 24, 173, primary.length() > 10 ? 20 : 28, BLUE, true);
            hudText(canvas, "VIEW / " + deviceView.toUpperCase(Locale.ROOT), 24, 234,
                    13, INK, true);
            hudText(canvas, "I2C " + deviceMpu.toUpperCase(Locale.ROOT), 24, 266,
                    12, MUTED, false);
            hudText(canvas, deviceBacklight ? "DISPLAY ONLINE" : "BACKLIGHT OFF",
                    24, 294, 12, deviceBacklight ? INK : RED, true);
            canvas.restore();
        }
    }

    private static final class CropImageView extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG |
                Paint.FILTER_BITMAP_FLAG);
        private final RectF cropWindow = new RectF();
        private Bitmap image;
        private float scale = 1f, minimumScale = 1f, offsetX, offsetY;
        private float lastX, lastY, pinchDistance;
        private boolean pinching;

        CropImageView(Context context) {
            super(context);
            setBackgroundColor(Color.rgb(18, 22, 31));
        }
        void setImage(Bitmap value) {
            image = value;
            if (getWidth() > 0) resetImage();
        }
        @Override protected void onSizeChanged(int width, int height, int oldWidth,
                                               int oldHeight) {
            float cropWidth = Math.min(width, height * .75f);
            float cropHeight = cropWidth * 4f / 3f;
            if (cropHeight > height) {
                cropHeight = height;
                cropWidth = cropHeight * .75f;
            }
            cropWindow.set((width - cropWidth) / 2f, (height - cropHeight) / 2f,
                    (width + cropWidth) / 2f, (height + cropHeight) / 2f);
            resetImage();
        }
        void resetImage() {
            if (image == null || cropWindow.width() <= 0) return;
            minimumScale = Math.max(cropWindow.width() / image.getWidth(),
                    cropWindow.height() / image.getHeight());
            scale = minimumScale;
            offsetX = cropWindow.centerX() - image.getWidth() * scale / 2f;
            offsetY = cropWindow.centerY() - image.getHeight() * scale / 2f;
            clamp();
            invalidate();
        }
        void setZoomPercent(int percent) {
            if (image == null || cropWindow.width() <= 0 || minimumScale <= 0) return;
            float focusX = cropWindow.centerX();
            float focusY = cropWindow.centerY();
            float sourceX = (focusX - offsetX) / scale;
            float sourceY = (focusY - offsetY) / scale;
            float nextScale = minimumScale * Math.max(100, Math.min(800, percent)) / 100f;
            offsetX = focusX - sourceX * nextScale;
            offsetY = focusY - sourceY * nextScale;
            scale = nextScale;
            clamp();
            invalidate();
        }
        RectF getSourceCrop() {
            if (image == null) return new RectF();
            return new RectF(
                    Math.max(0, (cropWindow.left - offsetX) / scale),
                    Math.max(0, (cropWindow.top - offsetY) / scale),
                    Math.min(image.getWidth(), (cropWindow.right - offsetX) / scale),
                    Math.min(image.getHeight(), (cropWindow.bottom - offsetY) / scale));
        }
        private void clamp() {
            if (image == null) return;
            float width = image.getWidth() * scale;
            float height = image.getHeight() * scale;
            offsetX = Math.min(cropWindow.left,
                    Math.max(cropWindow.right - width, offsetX));
            offsetY = Math.min(cropWindow.top,
                    Math.max(cropWindow.bottom - height, offsetY));
        }
        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            if (image == null) return;
            canvas.save();
            canvas.clipRect(cropWindow);
            Matrix matrix = new Matrix();
            matrix.setScale(scale, scale);
            matrix.postTranslate(offsetX, offsetY);
            canvas.drawBitmap(image, matrix, paint);
            canvas.restore();
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(4f);
            paint.setColor(Color.WHITE);
            canvas.drawRoundRect(cropWindow, 14f, 14f, paint);
            paint.setStyle(Paint.Style.FILL);
        }
        private static float distance(MotionEvent event) {
            if (event.getPointerCount() < 2) return 0;
            float dx = event.getX(0) - event.getX(1);
            float dy = event.getY(0) - event.getY(1);
            return (float) Math.sqrt(dx * dx + dy * dy);
        }
        @Override public boolean onTouchEvent(MotionEvent event) {
            if (image == null) return true;
            switch (event.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    if (getParent() != null) getParent().requestDisallowInterceptTouchEvent(true);
                    lastX = event.getX(); lastY = event.getY(); pinching = false; break;
                case MotionEvent.ACTION_POINTER_DOWN:
                    pinchDistance = distance(event); pinching = true; break;
                case MotionEvent.ACTION_MOVE:
                    if (event.getPointerCount() >= 2) {
                        float nextDistance = distance(event);
                        if (pinchDistance > 0 && nextDistance > 0) {
                            float focusX = (event.getX(0) + event.getX(1)) / 2f;
                            float focusY = (event.getY(0) + event.getY(1)) / 2f;
                            float sourceX = (focusX - offsetX) / scale;
                            float sourceY = (focusY - offsetY) / scale;
                            float nextScale = Math.max(minimumScale,
                                    Math.min(minimumScale * 8f,
                                            scale * nextDistance / pinchDistance));
                            offsetX = focusX - sourceX * nextScale;
                            offsetY = focusY - sourceY * nextScale;
                            scale = nextScale;
                            pinchDistance = nextDistance;
                        }
                    } else if (!pinching) {
                        offsetX += event.getX() - lastX;
                        offsetY += event.getY() - lastY;
                        lastX = event.getX(); lastY = event.getY();
                    }
                    clamp(); invalidate(); break;
                case MotionEvent.ACTION_POINTER_UP:
                    pinching = false;
                    if (event.getPointerCount() > 1) {
                        int remaining = event.getActionIndex() == 0 ? 1 : 0;
                        lastX = event.getX(remaining); lastY = event.getY(remaining);
                    }
                    break;
                case MotionEvent.ACTION_UP:
                case MotionEvent.ACTION_CANCEL:
                    pinching = false;
                    if (getParent() != null) getParent().requestDisallowInterceptTouchEvent(false);
                    break;
                default: break;
            }
            return true;
        }
    }

    private final class SecureStore {
        private static final String ALIAS = "LabCapsuleSecrets";
        void put(String key, String value) {
            try {
                KeyStore store = KeyStore.getInstance("AndroidKeyStore");
                store.load(null);
                if (!store.containsAlias(ALIAS)) {
                    KeyGenerator generator = KeyGenerator.getInstance(
                            KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
                    generator.init(new KeyGenParameterSpec.Builder(ALIAS,
                            KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
                    generator.generateKey();
                }
                SecretKey secret = ((KeyStore.SecretKeyEntry) store.getEntry(ALIAS, null))
                        .getSecretKey();
                Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                cipher.init(Cipher.ENCRYPT_MODE, secret);
                byte[] encrypted = cipher.doFinal(value.getBytes(StandardCharsets.UTF_8));
                preferences.edit().putString("secure_" + key,
                        android.util.Base64.encodeToString(cipher.getIV(),
                                android.util.Base64.NO_WRAP) + ":" +
                                android.util.Base64.encodeToString(encrypted,
                                        android.util.Base64.NO_WRAP)).apply();
            } catch (Exception error) { toast("安全存储失败：" + error.getMessage()); }
        }
        String get(String key) {
            try {
                String encoded = preferences.getString("secure_" + key, "");
                if (encoded.isEmpty()) return "";
                String[] parts = encoded.split(":", 2);
                KeyStore store = KeyStore.getInstance("AndroidKeyStore");
                store.load(null);
                SecretKey secret = ((KeyStore.SecretKeyEntry) store.getEntry(ALIAS, null))
                        .getSecretKey();
                Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                cipher.init(Cipher.DECRYPT_MODE, secret, new GCMParameterSpec(128,
                        android.util.Base64.decode(parts[0], android.util.Base64.NO_WRAP)));
                return new String(cipher.doFinal(android.util.Base64.decode(parts[1],
                        android.util.Base64.NO_WRAP)), StandardCharsets.UTF_8);
            } catch (Exception ignored) { return ""; }
        }
    }

    private final class LiquidNavBar extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private String[] items = new String[0];
        private int selected;
        private float indicator;
        private SelectionListener listener;
        LiquidNavBar(Activity context) {
            super(context);
            setLayerType(LAYER_TYPE_SOFTWARE, null);
        }
        void setItems(String[] labels) { items = labels; invalidate(); }
        void select(int index) {
            selected = Math.max(0, Math.min(items.length - 1, index));
            indicator = selected;
            invalidate();
        }
        @Override protected void onDraw(Canvas canvas) {
            float width = getWidth(), height = getHeight();
            RectF shell = new RectF(dp(3), dp(5), width - dp(3), height - dp(5));
            paint.setColor(Color.argb(appGlassOpacity * 255 / 100, Color.red(PANEL),
                    Color.green(PANEL), Color.blue(PANEL)));
            paint.setShadowLayer(dp(18), 0, dp(7), Color.argb(125, 0, 0, 0));
            canvas.drawRoundRect(shell, dp(28), dp(28), paint);
            paint.clearShadowLayer();
            if (items.length == 0) return;
            float cell = width / items.length;
            float center = (indicator + .5f) * cell;
            paint.setShader(new LinearGradient(center - cell * .42f, 0,
                    center + cell * .42f, height,
                    new int[]{Color.argb(240, Color.red(BLUE), Color.green(BLUE),
                            Color.blue(BLUE)), Color.argb(240, Color.red(SECONDARY),
                            Color.green(SECONDARY), Color.blue(SECONDARY))}, null,
                    Shader.TileMode.CLAMP));
            canvas.drawRoundRect(new RectF(center - cell * .42f, dp(10),
                    center + cell * .42f, height - dp(10)), dp(24), dp(24), paint);
            paint.setShader(null);
            paint.setTextAlign(Paint.Align.CENTER);
            paint.setTypeface(Typeface.DEFAULT_BOLD);
            for (int i = 0; i < items.length; ++i) {
                boolean active = i == selected;
                paint.setTextSize(dp(active ? 14 : 13));
                paint.setColor(active ? Color.rgb(16, 16, 16) : MUTED);
                canvas.drawText(items[i], (i + .5f) * cell,
                        height * .56f + (active ? dp(1) : dp(4)), paint);
                if (active) {
                    paint.setColor(Color.argb(180, 16, 16, 16));
                    canvas.drawCircle((i + .5f) * cell, height * .75f, dp(2), paint);
                }
            }
        }
        @Override public boolean onTouchEvent(MotionEvent event) {
            if (event.getAction() != MotionEvent.ACTION_UP || items.length == 0) return true;
            int next = Math.max(0, Math.min(items.length - 1,
                    (int) (event.getX() / (getWidth() / items.length))));
            if (next != selected) {
                float start = indicator;
                selected = next;
                ValueAnimator animator = ValueAnimator.ofFloat(start, next);
                animator.setDuration(360);
                animator.setInterpolator(new android.view.animation.OvershootInterpolator(.8f));
                animator.addUpdateListener(value -> {
                    indicator = (float) value.getAnimatedValue();
                    invalidate();
                });
                animator.start();
                if (listener != null) listener.changed(next);
            }
            return true;
        }
    }
    private interface IntValueListener { void changed(int value); }
    private interface SelectionListener { void changed(int index); }
}
