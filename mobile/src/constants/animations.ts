export const AnimationDurations = {
  fast: 200,
  normal: 300,
  slow: 500,
};

export const AnimationTimings = {
  linear: 'linear',
  easeIn: 'ease-in',
  easeOut: 'ease-out',
  easeInOut: 'ease-in-out',
  spring: 'spring',
};

export const FadeAnimationConfig = {
  duration: AnimationDurations.normal,
  damping: 20,
  stiffness: 90,
};

export const ScaleAnimationConfig = {
  duration: AnimationDurations.fast,
  damping: 15,
  stiffness: 150,
};

export const SlideAnimationConfig = {
  duration: AnimationDurations.normal,
  damping: 20,
  stiffness: 100,
};
