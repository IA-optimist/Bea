import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

class Viewer3DScreen extends StatefulWidget {
  const Viewer3DScreen({Key? key}) : super(key: key);

  @override
  State<Viewer3DScreen> createState() => _Viewer3DScreenState();
}

class _Viewer3DScreenState extends State<Viewer3DScreen> {
  late WebViewController _webViewController;
  bool _isLoading = true;
  bool _isConnected = false;
  
  @override
  void initState() {
    super.initState();
    _initializeWebView();
  }

  void _initializeWebView() {
    _webViewController = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(
        NavigationDelegate(
          onProgress: (int progress) {
            // Update loading indicator
            setState(() {
              _isLoading = true;
            });
          },
          onPageStarted: (String url) {
            setState(() {
              _isLoading = true;
            });
          },
          onPageFinished: (String url) {
            setState(() {
              _isLoading = false;
            });
            // Inject JavaScript to initialize 3D viewer
            _initialize3DViewer();
          },
          onWebResourceError: (WebResourceError error) {
            setState(() {
              _isLoading = false;
            });
            // Handle error
          },
        ),
      )
      ..loadRequest(Uri.parse('file:///android_asset/3d_viewer.html'));
  }

  void _initialize3DViewer() {
    // Inject JavaScript to initialize the 3D viewer
    _webViewController.runJavaScript('''
      if (typeof init3DViewer === 'function') {
        init3DViewer();
      }
    ''');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('3D Visualization'),
        backgroundColor: Theme.of(context).primaryColor,
        actions: [
          IconButton(
            icon: Icon(_isConnected ? Icons.connected : Icons.disconnected),
            onPressed: _toggleConnection,
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _refreshViewer,
          ),
        ],
      ),
      body: Stack(
        children: [
          WebViewWidget(controller: _webViewController),
          if (_isLoading)
            const Center(
              child: CircularProgressIndicator(),
            ),
        ],
      ),
      floatingActionButton: Column(
        mainAxisAlignment: MainAxisAlignment.end,
        children: [
          _buildFloatingActionButton(
            context,
            Icons.zoom_in,
            'Zoom In',
            () => _webViewController.runJavaScript('zoomIn()'),
          ),
          const SizedBox(height: 8),
          _buildFloatingActionButton(
            context,
            Icons.zoom_out,
            'Zoom Out',
            () => _webViewController.runJavaScript('zoomOut()'),
          ),
          const SizedBox(height: 8),
          _buildFloatingActionButton(
            context,
            Icons.rotate_right,
            'Rotate',
            () => _webViewController.runJavaScript('rotate()'),
          ),
          const SizedBox(height: 8),
          _buildFloatingActionButton(
            context,
            Icons.fullscreen,
            'Fullscreen',
            () => _webViewController.runJavaScript('toggleFullscreen()'),
          ),
        ],
      ),
    );
  }

  Widget _buildFloatingActionButton(
    BuildContext context,
    IconData icon,
    String tooltip,
    VoidCallback onPressed,
  ) {
    return FloatingActionButton(
      onPressed: onPressed,
      backgroundColor: Theme.of(context).primaryColor,
      child: Icon(icon),
      tooltip: tooltip,
    );
  }

  void _toggleConnection() {
    setState(() {
      _isConnected = !_isConnected;
    });
    
    if (_isConnected) {
      // Connect to WebSocket for real-time updates
      _webViewController.runJavaScript('connectWebSocket()');
    } else {
      // Disconnect from WebSocket
      _webViewController.runJavaScript('disconnectWebSocket()');
    }
  }

  void _refreshViewer() {
    setState(() {
      _isLoading = true;
    });
    _webViewController.reload();
  }
}