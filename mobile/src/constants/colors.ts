export const Colors = {
  light: {
    background: '#FFFFFF',
    surface: '#F5F5F5',
    card: '#FFFFFF',
    text: '#000000',
    textSecondary: '#666666',
    primary: '#5E6AD2',
    secondary: '#8B92B8',
    success: '#00D084',
    error: '#F5535D',
    warning: '#FFC043',
    info: '#4C9AFF',
    border: '#E5E5E5',
    shadow: '#00000010',
    overlay: '#00000050',
  },
  dark: {
    background: '#000000',
    surface: '#1A1A1A',
    card: '#2A2A2A',
    text: '#FFFFFF',
    textSecondary: '#999999',
    primary: '#7B83EB',
    secondary: '#9BA3CC',
    success: '#00D084',
    error: '#F5535D',
    warning: '#FFC043',
    info: '#4C9AFF',
    border: '#333333',
    shadow: '#FFFFFF10',
    overlay: '#00000080',
  },
};

export const Spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 24,
  xxxl: 32,
};

export const BorderRadius = {
  sm: 4,
  md: 8,
  lg: 12,
  xl: 16,
  round: 999,
};

export const Typography = {
  sizes: {
    xs: 12,
    sm: 14,
    md: 16,
    lg: 18,
    xl: 20,
    xxl: 24,
    xxxl: 32,
    display: 48,
  },
  weights: {
    regular: '400' as const,
    medium: '500' as const,
    semibold: '600' as const,
    bold: '700' as const,
  },
};

export const Shadows = {
  small: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 2,
  },
  medium: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 8,
    elevation: 3,
  },
  large: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.15,
    shadowRadius: 12,
    elevation: 5,
  },
};
