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
import android.view.*;
import android.widget.*;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
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
    private static final String APP_VERSION = "0.3.1";
    private static final String REPOSITORY = "81823650800wzy-sketch/LabCapsule";
    private static final int REQUEST_FIRMWARE = 1001, REQUEST_MEDIA = 1002,
            REQUEST_BLE_PERMISSIONS = 1003;

    private static final UUID SERVICE_UUID = uuid(1), COMMAND_UUID = uuid(2),
            STATUS_UUID = uuid(3), OTA_CONTROL_UUID = uuid(4), OTA_DATA_UUID = uuid(5),
            FILE_CONTROL_UUID = uuid(6), FILE_DATA_UUID = uuid(7);
    private static UUID uuid(int id) {
        return UUID.fromString(String.format(Locale.US,
                "6c4300%02d-4c61-6243-6170-73756c650001", id));
    }

    private static final int INK = Color.rgb(23, 31, 48), MUTED = Color.rgb(94, 108, 133),
            BLUE = Color.rgb(54, 112, 255), GREEN = Color.rgb(26, 153, 112),
            RED = Color.rgb(211, 69, 82);

    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private SharedPreferences preferences;
    private SecureStore secureStore;
    private FrameLayout content;
    private TextView globalStatus, mediaInfo, firmwareInfo, updateInfo, aiResult,
            externalWifiState, externalWifiIp, externalWifiHint;
    private ProgressBar globalProgress;
    private EditText deviceUrlInput, wifiSsid, wifiPassword, mqttUri, mqttUser, mqttPassword,
            mqttTopic, brightnessInput, aiEndpoint, aiModel, aiKey, aiQuestion;
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

    private BluetoothAdapter bluetoothAdapter;
    private BluetoothLeScanner bleScanner;
    private BluetoothGatt bluetoothGatt;
    private BluetoothGattCharacteristic commandCharacteristic, statusCharacteristic,
            otaControlCharacteristic, otaDataCharacteristic, fileControlCharacteristic,
            fileDataCharacteristic;
    private boolean bleReady, scanAfterPermission;
    private int bleMtu = 23, bleTransferOffset, blePendingLength;
    private byte[] bleTransferData;
    private String bleTransferPhase = "idle", bleTransferKind = "";
    private Runnable bleTransferCompletion;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        preferences = getSharedPreferences("labcapsule", MODE_PRIVATE);
        secureStore = new SecureStore();
        Window window = getWindow();
        window.setStatusBarColor(Color.TRANSPARENT);
        window.setNavigationBarColor(Color.TRANSPARENT);
        window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        if (Build.VERSION.SDK_INT >= 23) window.getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LAYOUT_STABLE |
                        View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN);
        BluetoothManager manager = (BluetoothManager) getSystemService(BLUETOOTH_SERVICE);
        bluetoothAdapter = manager == null ? null : manager.getAdapter();
        buildShell();
        showSection(0);
        if (preferences.getBoolean("auto_update", true)) checkForUpdates(true);
    }

    private void buildShell() {
        FrameLayout root = new FrameLayout(this);
        root.setBackground(new GradientDrawable(GradientDrawable.Orientation.TL_BR,
                new int[]{Color.rgb(232, 243, 255), Color.WHITE, Color.rgb(246, 239, 255)}));
        content = new FrameLayout(this);
        FrameLayout.LayoutParams cp = new FrameLayout.LayoutParams(-1, -1);
        cp.bottomMargin = dp(102);
        root.addView(content, cp);
        LiquidNavBar navigation = new LiquidNavBar(this);
        navigation.setItems(new String[]{"设备", "屏幕", "实验", "AI", "设置"});
        navigation.listener = this::showSection;
        FrameLayout.LayoutParams np = new FrameLayout.LayoutParams(-1, dp(82), Gravity.BOTTOM);
        np.setMargins(dp(14), 0, dp(14), dp(14));
        root.addView(navigation, np);
        setContentView(root);
    }

    private void showSection(int index) {
        gifStreaming = false;
        View page = index == 0 ? buildDevicePage() : index == 1 ? buildScreenPage()
                : index == 2 ? buildExperimentPage() : index == 3 ? buildAiPage()
                : buildSettingsPage();
        page.setAlpha(0f);
        page.setTranslationY(dp(18));
        content.removeAllViews();
        content.addView(page, new FrameLayout.LayoutParams(-1, -1));
        page.animate().alpha(1).translationY(0).setDuration(280).start();
    }

    private ScrollView page(String title, String subtitle) {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(18), dp(48), dp(18), dp(28));
        scroll.addView(root);
        root.addView(label(title, 31, INK, true));
        TextView sub = label(subtitle, 14, MUTED, false);
        sub.setPadding(0, dp(3), 0, dp(16));
        root.addView(sub);
        globalStatus = label("就绪", 13, MUTED, false);
        globalStatus.setPadding(dp(12), dp(10), dp(12), dp(10));
        globalStatus.setBackground(roundRect(Color.argb(150, 255, 255, 255), 15,
                Color.argb(45, 80, 110, 170)));
        root.addView(globalStatus, matchWrap(dp(10)));
        globalProgress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        globalProgress.setMax(100);
        globalProgress.setVisibility(View.GONE);
        root.addView(globalProgress, matchWrap(dp(8)));
        scroll.setTag(root);
        return scroll;
    }

    private LinearLayout pageRoot(ScrollView page) { return (LinearLayout) page.getTag(); }

    private View buildDevicePage() {
        ScrollView page = page("LabCapsule", "一个可扩展、可联网的实验实体小组件");
        LinearLayout root = pageRoot(page);
        LinearLayout hero = card(root, new int[]{Color.rgb(40, 92, 240), Color.rgb(126, 77, 255)});
        hero.addView(label("●  等待连接", 22, Color.WHITE, true));
        TextView hint = label("局域网、远程 MQTT 与 BLE 三种通道可并行使用", 13,
                Color.argb(220, 255, 255, 255), false);
        hint.setPadding(0, dp(7), 0, dp(6));
        hero.addView(hint);
        LinearLayout connection = card(root, null);
        section(connection, "连接中心", "手机无需停留在无互联网的设备热点");
        deviceUrlInput = input(preferences.getString("device_url", "http://192.168.4.1"),
                "设备 IP 或 URL", false);
        connection.addView(deviceUrlInput, matchWrap(0));
        transportSpinner = spinner(new String[]{"局域网 / Wi‑Fi", "Bluetooth LE"});
        transportSpinner.setSelection(preferences.getInt("transport", 0));
        connection.addView(transportSpinner, matchWrap(dp(6)));
        connection.addView(row(button("检测设备", true, v -> fetchStatus()),
                button("扫描 BLE", false, v -> startBleScan())));
        connection.addView(row(button("Wi‑Fi 系统设置", false,
                        v -> startActivity(new Intent(Settings.ACTION_WIFI_SETTINGS))),
                button("读取传感器", false, v -> fetchSensors())));
        LinearLayout wifiStatus = card(root, null);
        section(wifiStatus, "外部 Wi‑Fi 状态", "这里直接显示连接结果，不需要查找原始 JSON");
        externalWifiState = label("● 尚未读取设备状态", 17, MUTED, true);
        externalWifiIp = label("局域网 IP：尚未获取", 15, INK, false);
        externalWifiHint = label("先连接恢复热点并点击“检测设备”", 13, MUTED, false);
        externalWifiState.setPadding(0, 0, 0, dp(5));
        externalWifiIp.setTextIsSelectable(true);
        externalWifiHint.setPadding(0, dp(5), 0, dp(7));
        wifiStatus.addView(externalWifiState);
        wifiStatus.addView(externalWifiIp);
        wifiStatus.addView(externalWifiHint);
        wifiStatus.addView(row(button("刷新 Wi‑Fi 状态", true, v -> fetchStatus()),
                button("使用此局域网 IP", false, v -> useStationIp())));
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
        ScrollView page = page("屏幕与媒体", "静态壁纸、无落盘图片与 GIF 流式播放");
        LinearLayout root = pageRoot(page);
        LinearLayout media = card(root, null);
        section(media, "媒体工作台", "先触控裁剪；GIF 在手机端量化、差分和压缩");
        mediaPreview = new ImageView(this);
        mediaPreview.setScaleType(ImageView.ScaleType.CENTER_CROP);
        mediaPreview.setBackground(roundRect(Color.rgb(225, 232, 244), 18, Color.TRANSPARENT));
        media.addView(mediaPreview, new LinearLayout.LayoutParams(-1, dp(230)));
        mediaInfo = label("选择媒体后必须确认 3:4 裁剪区域", 13, MUTED, false);
        mediaInfo.setPadding(0, dp(9), 0, dp(4));
        media.addView(mediaInfo);
        transportSpinner = spinner(new String[]{"局域网 / Wi‑Fi", "Bluetooth LE"});
        transportSpinner.setSelection(preferences.getInt("transport", 0));
        media.addView(transportSpinner, matchWrap(dp(4)));
        media.addView(row(button("选择并裁剪", true, v -> chooseMedia()),
                button("重新裁剪", false, v -> reopenCropEditor()),
                button("显示单帧", false, v -> sendSelectedFrame())));
        media.addView(row(button("保存壁纸", false, v -> saveWallpaper()),
                button("播放 GIF", true, v -> startGifStream()),
                button("停止播放", false, v -> stopGifStream())));
        LinearLayout remote = card(root, null);
        section(remote, "屏幕遥控", "双缓冲切换不会先清黑屏");
        remote.addView(row(button("主页", false, v -> sendAction("home")),
                button("设置", false, v -> sendAction("settings")),
                button("开发诊断", false, v -> sendAction("developer"))));
        remote.addView(row(button("彩条", false, v -> sendAction("test")),
                button("壁纸", false, v -> sendAction("wallpaper")),
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
        ScrollView page = page("实验", "传感器发现、实验协议与固件生命周期");
        LinearLayout root = pageRoot(page);
        LinearLayout sensors = card(root, null);
        section(sensors, "传感器扩展", "运动、环境、电气、测距与模拟量驱动注册表");
        sensors.addView(label("GPIO8 / GPIO9 是扩展 I²C 总线。固件可发现 MPU6050、BME280、SHT3x、INA219、ADS1115、VL53L0X，并继续注册 SPI、UART、ADC、OneWire 驱动。", 14, INK, false));
        sensors.addView(row(button("扫描传感器", true, v -> fetchSensors()),
                button("刷新状态", false, v -> fetchStatus())));
        LinearLayout firmware = card(root, null);
        section(firmware, "固件更新", "双 OTA 分区，校验成功后才切换启动槽");
        transportSpinner = spinner(new String[]{"局域网 / Wi‑Fi", "Bluetooth LE"});
        transportSpinner.setSelection(preferences.getInt("transport", 0));
        firmware.addView(transportSpinner, matchWrap(0));
        firmwareInfo = label("尚未选择 .bin 固件", 13, MUTED, false);
        firmwareInfo.setPadding(0, dp(8), 0, dp(5));
        firmware.addView(firmwareInfo);
        firmware.addView(row(button("选择固件", false, v -> chooseFirmware()),
                button("开始 OTA", true, v -> startFirmwareUpdate())));
        firmware.addView(row(button("在线查找固件", false, v -> checkForUpdates(false)),
                button("下载最新固件", false, v -> downloadLatestFirmware())));
        return page;
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
        LinearLayout network = card(root, null);
        section(network, "外部 Wi‑Fi", "通过恢复热点配置一次，随后回到正常网络使用");
        wifiSsid = input(preferences.getString("wifi_ssid", ""), "路由器 SSID", false);
        wifiPassword = input(secureStore.get("wifi_password"), "路由器密码", true);
        network.addView(wifiSsid, matchWrap(0));
        network.addView(wifiPassword, matchWrap(dp(5)));
        keepRecoveryAp = check("保留 LabCapsule 恢复热点", preferences.getBoolean("keep_ap", true));
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
        section(about, "关于", "LabCapsule V0.3 · Motion Experiment Prototype");
        about.addView(label("默认语言：简体中文\n协议：HTTP + MQTT + BLE GATT\n屏幕：240×320 RGB565 双缓冲\n仓库：github.com/" + REPOSITORY, 13, MUTED, false));
        return page;
    }

    private LinearLayout card(LinearLayout parent, int[] gradient) {
        LinearLayout value = new LinearLayout(this);
        value.setOrientation(LinearLayout.VERTICAL);
        value.setPadding(dp(16), dp(16), dp(16), dp(16));
        GradientDrawable bg = gradient == null ? roundRect(Color.argb(218, 255, 255, 255),
                22, Color.argb(42, 70, 90, 140))
                : new GradientDrawable(GradientDrawable.Orientation.TL_BR, gradient);
        bg.setCornerRadius(dp(22));
        value.setBackground(bg);
        parent.addView(value, matchWrap(dp(13)));
        return value;
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
        view.setBackground(roundRect(Color.argb(150, 240, 245, 253), 14,
                Color.argb(35, 55, 80, 140)));
        if (password) view.setInputType(0x00000081);
        return view;
    }

    private Spinner spinner(String[] items) {
        Spinner spinner = new Spinner(this);
        spinner.setAdapter(new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_dropdown_item, items));
        spinner.setBackground(roundRect(Color.argb(150, 240, 245, 253), 14,
                Color.argb(35, 55, 80, 140)));
        return spinner;
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
        button.setTextColor(primary ? Color.WHITE : INK);
        button.setBackground(roundRect(primary ? BLUE : Color.argb(165, 236, 242, 252),
                15, primary ? Color.TRANSPARENT : Color.argb(35, 55, 80, 140)));
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
        int selected = transportSpinner == null ? preferences.getInt("transport", 0)
                : transportSpinner.getSelectedItemPosition();
        preferences.edit().putInt("transport", selected).apply();
        return selected;
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
        status("正在连接设备…", true);
        http("GET", "/api/status", null, null, result -> {
            try {
                JSONObject root = new JSONObject(result);
                JSONObject network = root.getJSONObject("network");
                renderExternalWifi(network.optBoolean("staConfigured"),
                        network.optBoolean("staConnected"),
                        network.optString("staIp", "0.0.0.0"),
                        network.optString("recoveryAp", "LabCapsule"));
                status("设备在线 · 网络状态已刷新", true);
            } catch (Exception error) {
                status("设备在线，但状态格式无法解析：" + error.getMessage(), false);
            }
        });
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
                    "手机现在可以切回正常联网 Wi‑Fi，再点击“使用此局域网 IP”。");
        } else if (configured) {
            lastStationIp = null;
            if (externalWifiState != null) {
                externalWifiState.setText("● 已保存配置，正在连接或连接失败");
                externalWifiState.setTextColor(Color.rgb(213, 132, 24));
            }
            if (externalWifiIp != null) externalWifiIp.setText("局域网 IP：尚未获取");
            if (externalWifiHint != null) externalWifiHint.setText(
                    "请确认是 2.4 GHz Wi‑Fi、密码正确，并保持连接 " + recoveryAp + " 后重试。");
        } else {
            lastStationIp = null;
            if (externalWifiState != null) {
                externalWifiState.setText("● 尚未配置外部 Wi‑Fi");
                externalWifiState.setTextColor(MUTED);
            }
            if (externalWifiIp != null) externalWifiIp.setText("局域网 IP：尚未获取");
            if (externalWifiHint != null) externalWifiHint.setText(
                    "进入“设置”填写路由器 SSID 与密码，然后返回这里刷新。");
        }
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
        http("GET", "/api/sensors", null, null,
                result -> status("传感器扫描完成\n" + result, true));
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
        BitmapFactory.Options options = new BitmapFactory.Options();
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
        TextView guide = label("拖动调整位置，双指缩放。白色框就是设备最终显示区域。", 13,
                MUTED, false);
        guide.setPadding(0, 0, 0, dp(8));
        layout.addView(guide);
        CropImageView editor = new CropImageView(this);
        editor.setImage(source);
        layout.addView(editor, new LinearLayout.LayoutParams(-1, dp(430)));
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
                    if (mediaInfo != null) mediaInfo.setText(name + " · 已裁剪 240×320 · " +
                            (movie == null ? "静态高质量" : "GIF 智能压缩"));
                    status("裁剪已确认，现在可以传输", true);
                }).create();
        cropDialog.setOnShowListener(dialog -> cropDialog.getButton(AlertDialog.BUTTON_NEUTRAL)
                .setOnClickListener(v -> editor.resetImage()));
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
        if (rle.length < raw.length) {
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
                    startBleFile("WALLPAPER", data, 0, null));
            else {
                try {
                    String response = httpBlocking("POST", endpoint + "/api/wallpaper",
                            data, "application/octet-stream", 45000);
                    runOnUiThread(() -> status("壁纸已保存\n" + response, true));
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
        if (gifStreaming) return;
        gifStreaming = true;
        lastGifComparisonFrame = null;
        status("GIF 智能流式播放：手机裁剪 + RGB332 + 差分 + RLE", true);
        if (selectedTransport() == 1) streamNextGifFrameBle(0);
        else {
            String endpoint = baseUrl();
            worker.execute(() -> streamGifWifi(selectedMovie, endpoint));
        }
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
        status("GIF 播放已停止", true);
    }
    private void startFirmwareUpdate() {
        if (selectedFirmware == null) { toast("请先选择固件"); return; }
        if (selectedTransport() == 1) startBleOta();
        else uploadBytes("/api/ota", selectedFirmware, "固件校验成功，设备正在重启");
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
        try {
            JSONObject protocol = new JSONObject(currentProtocol);
            int rate = protocol.getInt("sample_rate_hz");
            int duration = protocol.getInt("duration_seconds");
            status("正在下发实验协议…", true);
            if (selectedTransport() == 1) {
                writeBleCommand("START:" + rate + ":" + duration);
            } else {
                http("POST", "/api/experiment?rate=" + rate + "&duration=" + duration,
                        new byte[0], "application/octet-stream",
                        result -> status("实验已启动\n" + result, true));
            }
        } catch (Exception error) {
            status("协议无法执行：" + error.getMessage(), false);
        }
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
            bleReady = commandCharacteristic != null && statusCharacteristic != null &&
                    otaControlCharacteristic != null && otaDataCharacteristic != null &&
                    fileControlCharacteristic != null && fileDataCharacteristic != null;
            if (hasBlePermissions()) gatt.requestMtu(517);
            runOnUiThread(() -> status(bleReady ? "BLE 控制、OTA 与媒体通道已就绪"
                    : "BLE 特征不完整", bleReady));
        }
        @Override public void onMtuChanged(BluetoothGatt gatt, int mtu, int code) {
            if (code == BluetoothGatt.GATT_SUCCESS) bleMtu = mtu;
        }
        @Override @SuppressWarnings("deprecation") public void onCharacteristicRead(
                BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, int code) {
            handleBleRead(characteristic.getValue(), code);
        }
        @Override public void onCharacteristicRead(BluetoothGatt gatt,
                BluetoothGattCharacteristic characteristic, byte[] value, int code) {
            handleBleRead(value, code);
        }
        @Override public void onCharacteristicWrite(BluetoothGatt gatt,
                BluetoothGattCharacteristic characteristic, int code) {
            handleBleWrite(characteristic, code);
        }
    };
    private void handleBleRead(byte[] value, int code) {
        runOnUiThread(() -> status(code == BluetoothGatt.GATT_SUCCESS && value != null
                ? "BLE 在线\n" + new String(value, StandardCharsets.UTF_8)
                : "BLE 读取失败：" + code, code == BluetoothGatt.GATT_SUCCESS));
    }
    private void writeBleCommand(String command) {
        if (!bleReady || !"idle".equals(bleTransferPhase)) {
            status("BLE 未连接或正在传输", false); return;
        }
        if (!writeCharacteristic(commandCharacteristic,
                command.toUpperCase(Locale.ROOT).getBytes(StandardCharsets.UTF_8)))
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
        } else if ("idle".equals(bleTransferPhase)) {
            runOnUiThread(() -> status("BLE 指令已执行", true));
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
        gifStreaming = false;
        worker.shutdownNow();
        if (bleScanner != null && hasBlePermissions()) bleScanner.stopScan(scanCallback);
        if (bluetoothGatt != null && hasBlePermissions()) {
            bluetoothGatt.disconnect();
            bluetoothGatt.close();
        }
        super.onDestroy();
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
                                    Math.min(minimumScale * 5f,
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
                    pinching = false; break;
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
        @Override protected void onDraw(Canvas canvas) {
            float width = getWidth(), height = getHeight();
            RectF shell = new RectF(dp(3), dp(5), width - dp(3), height - dp(5));
            paint.setColor(Color.argb(205, 255, 255, 255));
            paint.setShadowLayer(dp(18), 0, dp(7), Color.argb(42, 55, 70, 120));
            canvas.drawRoundRect(shell, dp(28), dp(28), paint);
            paint.clearShadowLayer();
            if (items.length == 0) return;
            float cell = width / items.length;
            float center = (indicator + .5f) * cell;
            paint.setShader(new LinearGradient(center - cell * .42f, 0,
                    center + cell * .42f, height,
                    new int[]{Color.argb(225, 60, 140, 255),
                            Color.argb(225, 142, 75, 255)}, null, Shader.TileMode.CLAMP));
            canvas.drawRoundRect(new RectF(center - cell * .42f, dp(10),
                    center + cell * .42f, height - dp(10)), dp(24), dp(24), paint);
            paint.setShader(null);
            paint.setTextAlign(Paint.Align.CENTER);
            paint.setTypeface(Typeface.DEFAULT_BOLD);
            for (int i = 0; i < items.length; ++i) {
                boolean active = i == selected;
                paint.setTextSize(dp(active ? 14 : 13));
                paint.setColor(active ? Color.WHITE : MUTED);
                canvas.drawText(items[i], (i + .5f) * cell,
                        height * .56f + (active ? dp(1) : dp(4)), paint);
                if (active) {
                    paint.setColor(Color.argb(150, 255, 255, 255));
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
    private interface SelectionListener { void changed(int index); }
}
