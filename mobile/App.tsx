import { StatusBar } from "expo-status-bar";
import { ActivityIndicator, Linking, Platform, SafeAreaView, StyleSheet, Text, View } from "react-native";
import { WebView } from "react-native-webview";

export default function App() {
  const url = "https://cognisect.vercel.app";
  return (
    <SafeAreaView style={styles.container}>
      <StatusBar style="dark" />
      <WebView
        source={{ uri: url }}
        style={styles.webview}
        startInLoadingState
        renderLoading={() => <ActivityIndicator style={styles.loading} size="large" color="#0b6f68" />}
        allowsBackForwardNavigationGestures
        javaScriptEnabled
        domStorageEnabled
        setSupportMultipleWindows={false}
        onShouldStartLoadWithRequest={(request) => {
          if (request.url.startsWith("https://cognisect.vercel.app")) return true;
          if (Platform.OS === "ios" || Platform.OS === "android") void Linking.openURL(request.url);
          return false;
        }}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#efede5",
    paddingTop: Platform.OS === "android" ? 28 : 0,
  },
  webview: {
    flex: 1,
    backgroundColor: "#efede5",
  },
  loading: {
    flex: 1,
  },
});
