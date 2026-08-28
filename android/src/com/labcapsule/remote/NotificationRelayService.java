package com.labcapsule.remote;

import android.Manifest;
import android.app.Notification;
import android.bluetooth.*;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

import org.json.JSONObject;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Relays a privacy-controlled notification summary only while the device is idle. */
public final class NotificationRelayService extends NotificationListenerService {
    private static final UUID SERVICE_UUID = uuid(1), COMMAND_UUID = uuid(2);
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final Runnable delayedRelay = this::relayLatest;
    private SharedPreferences preferences;
    private BluetoothGatt gatt;
    private BluetoothGattCharacteristic command;
    private String latestTitle = "PHONE NOTICE", latestMessage = "NEW NOTIFICATION";
    private String[] commands;
    private int commandIndex;
    private boolean busy, relayAgain;

    private static UUID uuid(int id) {
        return UUID.fromString(String.format(Locale.US,
                "6c4300%02d-4c61-6243-6170-73756c650001", id));
    }

    @Override public void onCreate() {
        super.onCreate();
        preferences = getSharedPreferences("labcapsule", MODE_PRIVATE);
    }

    @Override public void onNotificationPosted(StatusBarNotification status) {
        if (status == null || getPackageName().equals(status.getPackageName()) ||
                !shouldRelay()) return;
        Notification notification = status.getNotification();
        if (notification == null || (notification.flags & Notification.FLAG_GROUP_SUMMARY) != 0)
            return;
        Bundle extras = notification.extras;
        String app = applicationName(status.getPackageName());
        String title = extras == null ? "" : text(extras.getCharSequence(
                Notification.EXTRA_TITLE));
        String message = extras == null ? "" : text(extras.getCharSequence(
                Notification.EXTRA_BIG_TEXT));
        if (message.isEmpty() && extras != null)
            message = text(extras.getCharSequence(Notification.EXTRA_TEXT));
        latestTitle = displayText(app + (title.isEmpty() ? "" : " " + title), 16,
                displayText(status.getPackageName(), 16, "PHONE NOTICE"));
        latestMessage = preferences.getBoolean("notification_relay_private", false)
                ? "NEW NOTIFICATION" : displayText(message, 32, "NEW NOTIFICATION");
        handler.removeCallbacks(delayedRelay);
        handler.postDelayed(delayedRelay, 650);
    }

    private boolean shouldRelay() {
        return preferences.getBoolean("notification_relay_enabled", false) &&
                "idle".equals(preferences.getString("operation_mode", "experiment")) &&
                !preferences.getBoolean("gif_service_running", false);
    }

    private void relayLatest() {
        if (!shouldRelay()) return;
        if (busy) { relayAgain = true; return; }
        busy = true;
        if (preferences.getInt("transport", 0) == 1) relayBle();
        else relayHttp(latestTitle, latestMessage);
    }

    private void relayHttp(String title, String message) {
        String endpoint = preferences.getString("device_url", "http://192.168.4.1");
        while (endpoint.endsWith("/")) endpoint = endpoint.substring(0, endpoint.length() - 1);
        final String url = endpoint + "/api/mode";
        worker.execute(() -> {
            HttpURLConnection connection = null;
            try {
                byte[] body = new JSONObject().put("mode", "idle").put("title", title)
                        .put("message", message).toString().getBytes(StandardCharsets.UTF_8);
                connection = (HttpURLConnection) new URL(url).openConnection();
                connection.setRequestMethod("POST");
                connection.setConnectTimeout(5000);
                connection.setReadTimeout(7000);
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/json");
                connection.setFixedLengthStreamingMode(body.length);
                try (OutputStream output = connection.getOutputStream()) { output.write(body); }
                int code = connection.getResponseCode();
                try (InputStream input = code >= 200 && code < 300
                        ? connection.getInputStream() : connection.getErrorStream()) {
                    if (input != null) while (input.read() >= 0) { }
                }
            } catch (Exception ignored) {
                // The next phone notification retries naturally; no noisy user notification.
            } finally {
                if (connection != null) connection.disconnect();
                handler.post(this::finishRelay);
            }
        });
    }

    private boolean hasConnectPermission() {
        return Build.VERSION.SDK_INT < 31 || checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)
                == PackageManager.PERMISSION_GRANTED;
    }

    private void relayBle() {
        String address = preferences.getString("ble_address", "");
        BluetoothManager manager = (BluetoothManager) getSystemService(Context.BLUETOOTH_SERVICE);
        BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
        if (!hasConnectPermission() || adapter == null || !adapter.isEnabled() || address.isEmpty()) {
            finishRelay();
            return;
        }
        commands = new String[]{"NOTICE:" + latestTitle + "|" + latestMessage, "MODE:IDLE"};
        commandIndex = 0;
        try {
            gatt = adapter.getRemoteDevice(address).connectGatt(this, false, callback,
                    BluetoothDevice.TRANSPORT_LE);
            final BluetoothGatt scheduledGatt = gatt;
            handler.postDelayed(() -> {
                if (busy && gatt == scheduledGatt) finishRelay();
            }, 12000);
        } catch (Exception ignored) { finishRelay(); }
    }

    private final BluetoothGattCallback callback = new BluetoothGattCallback() {
        @Override public void onConnectionStateChange(BluetoothGatt value, int status, int state) {
            if (value != gatt) return;
            if (status == BluetoothGatt.GATT_SUCCESS && state == BluetoothProfile.STATE_CONNECTED) {
                if (hasConnectPermission()) value.discoverServices();
            } else if (state == BluetoothProfile.STATE_DISCONNECTED) finishRelay();
        }

        @Override public void onServicesDiscovered(BluetoothGatt value, int status) {
            BluetoothGattService service = status == BluetoothGatt.GATT_SUCCESS
                    ? value.getService(SERVICE_UUID) : null;
            command = service == null ? null : service.getCharacteristic(COMMAND_UUID);
            if (command == null || !writeNext()) finishRelay();
        }

        @Override public void onCharacteristicWrite(BluetoothGatt value,
                BluetoothGattCharacteristic characteristic, int status) {
            if (status != BluetoothGatt.GATT_SUCCESS || !writeNext()) finishRelay();
        }
    };

    @SuppressWarnings("deprecation")
    private boolean writeNext() {
        if (gatt == null || command == null || commands == null ||
                commandIndex >= commands.length || !hasConnectPermission()) return false;
        byte[] value = commands[commandIndex++].getBytes(StandardCharsets.US_ASCII);
        if (Build.VERSION.SDK_INT >= 33) return gatt.writeCharacteristic(command, value,
                BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) == 0;
        command.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
        command.setValue(value);
        return gatt.writeCharacteristic(command);
    }

    private void finishRelay() {
        BluetoothGatt closing = gatt;
        gatt = null;
        command = null;
        commands = null;
        if (closing != null && hasConnectPermission()) {
            closing.disconnect();
            closing.close();
        }
        busy = false;
        if (relayAgain) {
            relayAgain = false;
            handler.postDelayed(delayedRelay, 300);
        }
    }

    private String applicationName(String packageName) {
        try {
            PackageManager manager = getPackageManager();
            ApplicationInfo info = manager.getApplicationInfo(packageName, 0);
            return text(manager.getApplicationLabel(info));
        } catch (Exception ignored) { return packageName; }
    }

    private static String text(CharSequence value) {
        return value == null ? "" : value.toString().trim();
    }

    private static String displayText(String source, int maximum, String fallback) {
        StringBuilder result = new StringBuilder();
        boolean priorSpace = false;
        for (int index = 0; source != null && index < source.length() &&
                result.length() < maximum; ++index) {
            char value = Character.toUpperCase(source.charAt(index));
            char output = ((value >= 'A' && value <= 'Z') || (value >= '0' && value <= '9') ||
                    value == '-' || value == '.' || value == ':') ? value : ' ';
            if (output == ' ' && (result.length() == 0 || priorSpace)) continue;
            result.append(output);
            priorSpace = output == ' ';
        }
        String normalized = result.toString().trim();
        return normalized.isEmpty() ? fallback : normalized;
    }

    @Override public void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        finishRelay();
        worker.shutdownNow();
        super.onDestroy();
    }
}
