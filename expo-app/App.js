// Unit Non-CSD App — Expo Go wrapper.
// Opens the store (or the owner dashboard) that is running on your computer, inside Expo Go.
// Which one opens depends on the QR code scanned:  exp://<ip>:8081/--/store  or  exp://<ip>:8081/--/admin
import React, { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, BackHandler, Platform, StatusBar, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { WebView } from "react-native-webview";
import Constants from "expo-constants";
import * as Linking from "expo-linking";

const APP_PORT = 8000; // port of the Unit Non-CSD App server (run.py)

function serverBase() {
  // Expo tells us the address of the computer running "npx expo start"; the app server runs on the same computer.
  const hostUri = (Constants.expoConfig && Constants.expoConfig.hostUri) || (Constants.manifest2 && Constants.manifest2.extra && Constants.manifest2.extra.expoGo && Constants.manifest2.extra.expoGo.debuggerHost) || "";
  const host = hostUri.split(":")[0] || "192.168.1.2";
  return `http://${host}:${APP_PORT}`;
}

const pathFor = (url) => (url && url.includes("/--/admin") ? "/admin" : "/");

export default function App() {
  const web = useRef(null);
  const [path, setPath] = useState(null);
  const [canGoBack, setCanGoBack] = useState(false);
  const [error, setError] = useState(false);
  const [key, setKey] = useState(0);
  const base = serverBase();

  useEffect(() => {
    Linking.getInitialURL().then((u) => setPath(pathFor(u)));
    const sub = Linking.addEventListener("url", ({ url }) => { setPath(pathFor(url)); setKey((k) => k + 1); });
    return () => sub.remove();
  }, []);

  useEffect(() => {
    if (Platform.OS !== "android") return;
    const h = BackHandler.addEventListener("hardwareBackPress", () => {
      if (canGoBack && web.current) { web.current.goBack(); return true; }
      return false;
    });
    return () => h.remove();
  }, [canGoBack]);

  const retry = useCallback(() => { setError(false); setKey((k) => k + 1); }, []);

  if (path === null) return <View style={s.center}><ActivityIndicator size="large" color="#1f8a8a" /></View>;

  return (
    <View style={s.wrap}>
      <StatusBar barStyle="light-content" backgroundColor="#2b3047" />
      <View style={s.bar} />
      {error ? (
        <View style={s.center}>
          <Text style={s.h}>Can't reach the store</Text>
          <Text style={s.p}>Make sure the Unit Non-CSD App is running on your computer ({base}) and that this phone is on the same Wi-Fi.</Text>
          <TouchableOpacity style={s.btn} onPress={retry}><Text style={s.btnT}>Try again</Text></TouchableOpacity>
        </View>
      ) : (
        <WebView
          key={key}
          ref={web}
          source={{ uri: base + path }}
          startInLoadingState
          renderLoading={() => <View style={s.center}><ActivityIndicator size="large" color="#1f8a8a" /></View>}
          onNavigationStateChange={(n) => setCanGoBack(n.canGoBack)}
          onError={() => setError(true)}
          onHttpError={(e) => { if (e.nativeEvent.statusCode >= 500) setError(true); }}
          sharedCookiesEnabled
          domStorageEnabled
          javaScriptEnabled
          pullToRefreshEnabled
          setSupportMultipleWindows={false}
        />
      )}
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#ffffff" },
  bar: { height: Platform.OS === "android" ? StatusBar.currentHeight || 24 : 48, backgroundColor: "#2b3047" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24, backgroundColor: "#ffffff" },
  h: { fontSize: 20, fontWeight: "700", color: "#1d1f2b", marginBottom: 8 },
  p: { fontSize: 15, color: "#4a4e60", textAlign: "center", marginBottom: 18 },
  btn: { backgroundColor: "#1f8a8a", paddingVertical: 12, paddingHorizontal: 22, borderRadius: 10 },
  btnT: { color: "#fff", fontWeight: "700", fontSize: 16 },
});
