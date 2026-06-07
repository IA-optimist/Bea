import { Brain, Zap } from 'lucide-react';
import { motion } from 'framer-motion';

interface LogoProps {
  size?: 'sm' | 'md' | 'lg';
  showText?: boolean;
  animated?: boolean;
}

export const Logo = ({ size = 'md', showText = true, animated = false }: LogoProps) => {
  const sizeClasses = {
    sm: 'w-8 h-8',
    md: 'w-12 h-12',
    lg: 'w-16 h-16',
  };

  const textSizeClasses = {
    sm: 'text-lg',
    md: 'text-2xl',
    lg: 'text-4xl',
  };

  const LogoIcon = animated ? motion.div : 'div';

  return (
    <div className="flex items-center gap-3">
      <LogoIcon
        className={`${sizeClasses[size]} bg-gradient-to-br from-primary-500 via-purple-600 to-blue-600 rounded-xl flex items-center justify-center shadow-lg relative overflow-hidden`}
        {...(animated && {
          animate: {
            boxShadow: [
              '0 10px 25px -5px rgba(99, 102, 241, 0.3)',
              '0 10px 30px -5px rgba(99, 102, 241, 0.5)',
              '0 10px 25px -5px rgba(99, 102, 241, 0.3)',
            ],
          },
          transition: {
            duration: 3,
            repeat: Infinity,
            ease: 'easeInOut',
          },
        })}
      >
        {/* Neural network pulse effect */}
        {animated && (
          <motion.div
            className="absolute inset-0 bg-gradient-to-br from-white/30 to-transparent"
            animate={{
              opacity: [0.3, 0.6, 0.3],
              scale: [1, 1.1, 1],
            }}
            transition={{
              duration: 2,
              repeat: Infinity,
              ease: 'easeInOut',
            }}
          />
        )}
        
        <div className="relative z-10 flex items-center justify-center">
          <Brain className="w-1/2 h-1/2 text-white" strokeWidth={2.5} />
          <Zap 
            className="absolute w-1/3 h-1/3 text-yellow-300" 
            strokeWidth={3}
            style={{ transform: 'translate(25%, 25%)' }}
          />
        </div>
      </LogoIcon>

      {showText && (
        <div>
          <h1 className={`${textSizeClasses[size]} font-bold bg-gradient-to-r from-primary-600 via-purple-600 to-blue-600 bg-clip-text text-transparent`}>
            BeaMax
          </h1>
          <p className="text-xs text-gray-500 dark:text-gray-400 font-medium tracking-wider">
            AI OPERATING SYSTEM
          </p>
        </div>
      )}
    </div>
  );
};
