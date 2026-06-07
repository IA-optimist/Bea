/// BeaMax UI modes — progressive disclosure.
enum AppMode {
  lite,   // simple daily use
  full,   // power-user
  admin,  // builder/operator
}

extension AppModeX on AppMode {
  String get label => switch (this) {
    AppMode.lite  => 'Lite',
    AppMode.full  => 'Full',
    AppMode.admin => 'Admin',
  };

  String get description => switch (this) {
    AppMode.lite  => 'Simple, focused daily use',
    AppMode.full  => 'Full power-user controls',
    AppMode.admin => 'Builder & operator tools',
  };

  bool get showOperations => this == AppMode.full || this == AppMode.admin;
  bool get showSystem => this == AppMode.admin;
}
