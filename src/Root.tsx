import React from 'react';
import {Composition} from 'remotion';
import {Video} from './Video';
import {defaultProps, VideoProps} from './types';

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="Main"
      component={Video}
      width={1080}
      height={1920}
      fps={30}
      durationInFrames={30}
      defaultProps={defaultProps}
      calculateMetadata={({props}: {props: VideoProps}) => {
        const total = props.scenes.reduce((sum, s) => sum + s.durationInFrames, 0);
        return {
          durationInFrames: Math.max(1, total),
          fps: props.fps || 30,
        };
      }}
    />
  );
};
