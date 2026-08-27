package com.labcapsule.remote;

import android.Manifest;
import android.app.*;
import android.bluetooth.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.net.wifi.WifiManager;
import android.os.*;

import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.zip.CRC32;

public final class GifPlaybackService extends Service {
    public static final String ACTION_START = "com.labcapsule.remote.GIF_START";
    public static final String ACTION_PREPARE = "com.labcapsule.remote.GIF_PREPARE";
    public static final String ACTION_STOP = "com.labcapsule.remote.GIF_STOP";
    public static final String EXTRA_FILE = "file";
    public static final String EXTRA_TRANSPORT = "transport";
    public static final String EXTRA_ENDPOINT = "endpoint";
    public static final String EXTRA_BLE_ADDRESS = "ble_address";
    public static final int CLIP_MAGIC = 0x4C434734;
    public static final int CLIP_VERSION = 1;

    private static final String CHANNEL_ID = "labcapsule_gif";
    private static final int NOTIFICATION_ID = 4304;
    private static final UUID SERVICE_UUID = uuid(1), FILE_CONTROL_UUID = uuid(6),
            FILE_DATA_UUID = uuid(7);

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private volatile boolean running;
    private int generation;
    private String clipPath, endpoint, bleAddress;
    private int transport;
    private PowerManager.WakeLock wakeLock;
    private WifiManager.WifiLock wifiLock;
    private BluetoothGatt gatt;
    private BluetoothGattCharacteristic fileControl, fileData;
    private ClipReader bleClip;
    private ClipFrame bleFrame;
    private int bleMtu = 23, bleOffset, blePending;
    private long bleFrameStarted;
    private String blePhase = "idle";

    private static UUID uuid(int id) {
        return UUID.fromString(String.format(Locale.US,
                "6c4300%02d-4c61-6243-6170-73756c650001", id));
    }

    @Override public void onCreate() {
        super.onCreate();
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (Build.VERSION.SDK_INT >= 26 && manager != null) {
            NotificationChannel channel = new NotificationChannel(CHANNEL_ID,
                    "GIF 后台播放", NotificationManager.IMPORTANCE_LOW);
            channel.setDescription("保持 LabCapsule 动态壁纸传输");
            manager.createNotificationChannel(channel);
        }
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            stopPlayback("已停止");
            stopSelf();
            return START_NOT_STICKY;
        }
        if (intent != null && ACTION_PREPARE.equals(intent.getAction())) {
            startForeground(NOTIFICATION_ID, notification("正在预处理 GIF 播放缓存…"));
            updateState(true, "正在预处理 GIF 播放缓存");
            int token = ++generation;
            handler.postDelayed(() -> {
                if (!running && token == generation) {
                    updateState(false, "GIF 预处理超时");
                    stopSelf();
                }
            }, 120000);
            return START_NOT_STICKY;
        }
        SharedPreferences preferences = getSharedPreferences("labcapsule", MODE_PRIVATE);
        if (intent != null) {
            clipPath = intent.getStringExtra(EXTRA_FILE);
            endpoint = intent.getStringExtra(EXTRA_ENDPOINT);
            bleAddress = intent.getStringExtra(EXTRA_BLE_ADDRESS);
            transport = intent.getIntExtra(EXTRA_TRANSPORT, 0);
        } else {
            clipPath = preferences.getString("gif_clip", "");
            endpoint = preferences.getString("gif_endpoint", "");
            bleAddress = preferences.getString("gif_ble_address", "");
            transport = preferences.getInt("gif_transport", 0);
        }
        startForeground(NOTIFICATION_ID, notification("正在启动后台播放器…"));
        if (clipPath == null || !new File(clipPath).isFile()) {
            updateState(false, "播放缓存不存在");
            stopSelf();
            return START_NOT_STICKY;
        }
        stopTransport();
        releaseLocks();
        running = true;
        int token = ++generation;
        preferences.edit().putString("gif_clip", clipPath)
                .putString("gif_endpoint", endpoint == null ? "" : endpoint)
                .putString("gif_ble_address", bleAddress == null ? "" : bleAddress)
                .putInt("gif_transport", transport).apply();
        acquireLocks();
        updateState(true, transport == 1 ? "BLE 后台播放器正在连接" : "Wi‑Fi 后台播放中");
        if (transport == 1) connectBle(token); else worker.execute(() -> playWifi(token));
        return START_REDELIVER_INTENT;
    }

    private void acquireLocks() {
        PowerManager power = (PowerManager) getSystemService(POWER_SERVICE);
        if (power != null) {
            wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,
                    "LabCapsule:GifPlayback");
            wakeLock.acquire();
        }
        if (transport == 0) {
            WifiManager wifi = (WifiManager) getApplicationContext().getSystemService(WIFI_SERVICE);
            if (wifi != null) {
                wifiLock = wifi.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF,
                        "LabCapsuleGif");
                wifiLock.acquire();
            }
        }
    }

    private void releaseLocks() {
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        if (wifiLock != null && wifiLock.isHeld()) wifiLock.release();
        wakeLock = null;
        wifiLock = null;
    }

    private Notification notification(String message) {
        Intent open = new Intent(this, MainActivity.class);
        PendingIntent openIntent = PendingIntent.getActivity(this, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Intent stop = new Intent(this, GifPlaybackService.class).setAction(ACTION_STOP);
        PendingIntent stopIntent = PendingIntent.getService(this, 1, stop,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_media_play)
                .setContentTitle("LabCapsule 动态壁纸")
                .setContentText(message)
                .setOngoing(true).setOnlyAlertOnce(true)
                .setContentIntent(openIntent)
                .addAction(new Notification.Action.Builder(android.R.drawable.ic_media_pause,
                        "停止", stopIntent).build())
                .build();
    }

    private void updateState(boolean active, String message) {
        getSharedPreferences("labcapsule", MODE_PRIVATE).edit()
                .putBoolean("gif_service_running", active)
                .putString("gif_service_message", message).apply();
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null && active) manager.notify(NOTIFICATION_ID, notification(message));
    }

    private void playWifi(int token) {
        int displayed = 0;
        try (ClipReader clip = new ClipReader(new File(clipPath))) {
            ClipFrame frame = clip.bootstrap;
            while (running && token == generation) {
                long started = SystemClock.elapsedRealtime();
                if (frame.data.length > 0) postHttpFrame(frame, clip.intervalMs);
                ++displayed;
                if (displayed % 12 == 0)
                    updateState(true, "Wi‑Fi 后台播放 · 已发送 " + displayed + " 帧");
                long remaining = clip.intervalMs - (SystemClock.elapsedRealtime() - started);
                if (remaining > 0) Thread.sleep(remaining);
                frame = clip.nextLoopFrame();
            }
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        } catch (Exception error) {
            if (running && token == generation) {
                updateState(true, "Wi‑Fi 播放暂停，2 秒后重试：" + shortMessage(error));
                handler.postDelayed(() -> {
                    if (running && token == generation) worker.execute(() -> playWifi(token));
                }, 2000);
            }
        }
    }

    private void postHttpFrame(ClipFrame frame, int duration) throws Exception {
        String path = String.format(Locale.US,
                "/api/media/frame?duration=%d&enc=%s&x=%d&y=%d&w=%d&h=%d",
                duration, frame.encoding, frame.x, frame.y, frame.width, frame.height);
        HttpURLConnection connection = (HttpURLConnection) new URL(endpoint + path).openConnection();
        try {
            connection.setRequestMethod("POST");
            connection.setConnectTimeout(5000);
            connection.setReadTimeout(15000);
            connection.setDoOutput(true);
            connection.setUseCaches(false);
            connection.setRequestProperty("Content-Type", "application/octet-stream");
            connection.setRequestProperty("Connection", "keep-alive");
            connection.setFixedLengthStreamingMode(frame.data.length);
            try (OutputStream output = connection.getOutputStream()) { output.write(frame.data); }
            int code = connection.getResponseCode();
            try (InputStream input = code >= 200 && code < 300
                    ? connection.getInputStream() : connection.getErrorStream()) {
                if (input != null) while (input.read() >= 0) { }
            }
            if (code < 200 || code >= 300) throw new IOException("HTTP " + code);
        } finally { connection.disconnect(); }
    }

    private boolean hasBlePermission() {
        return Build.VERSION.SDK_INT < 31 || checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)
                == PackageManager.PERMISSION_GRANTED;
    }

    private void connectBle(int token) {
        if (!running || token != generation || !hasBlePermission()) {
            updateState(false, "BLE 权限不可用");
            stopSelf();
            return;
        }
        try {
            BluetoothManager manager = (BluetoothManager) getSystemService(BLUETOOTH_SERVICE);
            BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
            if (adapter == null || !adapter.isEnabled() || bleAddress == null ||
                    bleAddress.isEmpty()) throw new IOException("没有可重连的 BLE 设备");
            gatt = adapter.getRemoteDevice(bleAddress).connectGatt(this, false, gattCallback,
                    BluetoothDevice.TRANSPORT_LE);
        } catch (Exception error) { scheduleBleReconnect(token, shortMessage(error)); }
    }

    private final BluetoothGattCallback gattCallback = new BluetoothGattCallback() {
        @Override public void onConnectionStateChange(BluetoothGatt value, int status, int state) {
            if (!running || value != gatt) return;
            if (status == BluetoothGatt.GATT_SUCCESS && state == BluetoothProfile.STATE_CONNECTED) {
                updateState(true, "BLE 已连接，正在准备动态壁纸");
                if (hasBlePermission()) value.discoverServices();
            } else if (state == BluetoothProfile.STATE_DISCONNECTED) {
                closeGatt();
                scheduleBleReconnect(generation, "连接断开");
            }
        }
        @Override public void onServicesDiscovered(BluetoothGatt value, int status) {
            BluetoothGattService service = status == BluetoothGatt.GATT_SUCCESS
                    ? value.getService(SERVICE_UUID) : null;
            if (service == null) { scheduleBleReconnect(generation, "媒体服务不可用"); return; }
            fileControl = service.getCharacteristic(FILE_CONTROL_UUID);
            fileData = service.getCharacteristic(FILE_DATA_UUID);
            if (fileControl == null || fileData == null) {
                scheduleBleReconnect(generation, "媒体特征不完整"); return;
            }
            if (!hasBlePermission() || !value.requestMtu(517)) startBleClip();
        }
        @Override public void onMtuChanged(BluetoothGatt value, int mtu, int status) {
            if (status == BluetoothGatt.GATT_SUCCESS) bleMtu = mtu;
            startBleClip();
        }
        @Override public void onCharacteristicWrite(BluetoothGatt value,
                BluetoothGattCharacteristic characteristic, int status) {
            if (!running) return;
            if (status != BluetoothGatt.GATT_SUCCESS) {
                scheduleBleReconnect(generation, "写入失败 " + status); return;
            }
            UUID uuid = characteristic.getUuid();
            if ("begin".equals(blePhase) && uuid.equals(FILE_CONTROL_UUID)) {
                blePhase = "data";
                writeNextBleChunk();
            } else if ("data".equals(blePhase) && uuid.equals(FILE_DATA_UUID)) {
                bleOffset += blePending;
                if (bleOffset >= bleFrame.data.length) {
                    blePhase = "end";
                    write(fileControl, "END".getBytes(StandardCharsets.UTF_8));
                } else writeNextBleChunk();
            } else if ("end".equals(blePhase) && uuid.equals(FILE_CONTROL_UUID)) {
                blePhase = "idle";
                long remaining = bleClip.intervalMs -
                        (SystemClock.elapsedRealtime() - bleFrameStarted);
                handler.postDelayed(() -> sendNextBleFrame(generation), Math.max(20, remaining));
            }
        }
    };

    private void startBleClip() {
        try {
            if (bleClip != null) bleClip.close();
            bleClip = new ClipReader(new File(clipPath));
            bleFrame = bleClip.bootstrap;
            updateState(true, "BLE 后台播放中 · 稀疏差分已启用");
            sendBleFrame(bleFrame);
        } catch (Exception error) { scheduleBleReconnect(generation, shortMessage(error)); }
    }

    private void sendNextBleFrame(int token) {
        if (!running || token != generation || bleClip == null) return;
        try {
            ClipFrame frame = bleClip.nextLoopFrame();
            if (frame.data.length == 0) {
                handler.postDelayed(() -> sendNextBleFrame(token), bleClip.intervalMs);
            } else sendBleFrame(frame);
        } catch (Exception error) { scheduleBleReconnect(token, shortMessage(error)); }
    }

    private void sendBleFrame(ClipFrame frame) {
        bleFrame = frame;
        bleOffset = 0;
        bleFrameStarted = SystemClock.elapsedRealtime();
        CRC32 crc = new CRC32();
        crc.update(frame.data);
        String begin = String.format(Locale.US,
                "BEGIN:FRAME:%d:%d:%08X:%s:%d:%d:%d:%d", frame.data.length,
                bleClip.intervalMs, crc.getValue(), frame.encoding, frame.x, frame.y,
                frame.width, frame.height);
        blePhase = "begin";
        if (!write(fileControl, begin.getBytes(StandardCharsets.UTF_8)))
            scheduleBleReconnect(generation, "无法提交帧");
    }

    private void writeNextBleChunk() {
        int chunk = Math.max(20, Math.min(500, bleMtu - 3));
        blePending = Math.min(chunk, bleFrame.data.length - bleOffset);
        byte[] data = new byte[blePending];
        System.arraycopy(bleFrame.data, bleOffset, data, 0, blePending);
        if (!write(fileData, data)) scheduleBleReconnect(generation, "传输队列失败");
    }

    @SuppressWarnings("deprecation")
    private boolean write(BluetoothGattCharacteristic characteristic, byte[] value) {
        if (gatt == null || characteristic == null || !hasBlePermission()) return false;
        if (Build.VERSION.SDK_INT >= 33) return gatt.writeCharacteristic(characteristic,
                value, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) == 0;
        characteristic.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
        characteristic.setValue(value);
        return gatt.writeCharacteristic(characteristic);
    }

    private void scheduleBleReconnect(int token, String reason) {
        if (!running || token != generation) return;
        closeGatt();
        updateState(true, "BLE 暂停，2 秒后重连：" + reason);
        handler.postDelayed(() -> connectBle(token), 2000);
    }

    private void closeGatt() {
        BluetoothGatt closing = gatt;
        gatt = null;
        if (closing != null && hasBlePermission()) {
            closing.disconnect();
            closing.close();
        }
        fileControl = fileData = null;
        try { if (bleClip != null) bleClip.close(); } catch (Exception ignored) { }
        bleClip = null;
    }

    private void stopTransport() {
        running = false;
        ++generation;
        handler.removeCallbacksAndMessages(null);
        closeGatt();
    }

    private void stopPlayback(String message) {
        stopTransport();
        releaseLocks();
        updateState(false, message);
        stopForeground(true);
    }

    @Override public void onDestroy() {
        stopPlayback("后台播放器已结束");
        worker.shutdownNow();
        super.onDestroy();
    }

    @Override public android.os.IBinder onBind(Intent intent) { return null; }

    private static String shortMessage(Throwable error) {
        String value = error == null ? "未知错误" : error.getMessage();
        return value == null || value.isEmpty() ? error.getClass().getSimpleName() : value;
    }

    private static final class ClipFrame {
        String encoding;
        int x, y, width, height;
        byte[] data;
    }

    private static final class ClipReader implements Closeable {
        final RandomAccessFile file;
        final int intervalMs, loopFrameCount;
        final long loopOffset;
        final ClipFrame bootstrap;
        int loopIndex;

        ClipReader(File source) throws Exception {
            file = new RandomAccessFile(source, "r");
            if (file.readInt() != CLIP_MAGIC || file.readInt() != CLIP_VERSION)
                throw new IOException("GIF 缓存版本不兼容");
            intervalMs = file.readInt();
            loopFrameCount = file.readInt();
            if (intervalMs < 40 || loopFrameCount < 1 || loopFrameCount > 600)
                throw new IOException("GIF 缓存头无效");
            bootstrap = readFrame(file);
            loopOffset = file.getFilePointer();
        }

        ClipFrame nextLoopFrame() throws Exception {
            if (loopIndex >= loopFrameCount) {
                file.seek(loopOffset);
                loopIndex = 0;
            }
            ++loopIndex;
            return readFrame(file);
        }

        @Override public void close() throws IOException { file.close(); }

        private static ClipFrame readFrame(RandomAccessFile input) throws Exception {
            ClipFrame frame = new ClipFrame();
            int encoding = input.readUnsignedByte();
            frame.encoding = encoding == 1 ? "rgb332" : encoding == 2 ? "rle332" :
                    encoding == 3 ? "delta332" : "rgb332";
            frame.x = input.readUnsignedShort();
            frame.y = input.readUnsignedShort();
            frame.width = input.readUnsignedShort();
            frame.height = input.readUnsignedShort();
            int length = input.readInt();
            if (frame.x + frame.width > 240 || frame.y + frame.height > 320 ||
                    length < 0 || length > 153600) throw new IOException("GIF 帧无效");
            frame.data = new byte[length];
            input.readFully(frame.data);
            return frame;
        }
    }
}
