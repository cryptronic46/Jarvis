type Props = {
  ambient: boolean;
};

export default function JarvisCoreVisual({ ambient }: Props) {
  return (
    <div
      className={`coreScene ${ambient ? "ambient" : "idle"}`}
      aria-hidden="true"
    >
      <div className="spaceGlow" />
      <div className="starField starFieldOne" />
      <div className="starField starFieldTwo" />
      <div className="hudGrid" />

      <div className="earthAtmosphere" />
      <div className="earthHorizon" />

      <div className="coreReticle reticleOuter" />
      <div className="coreReticle reticleMid" />
      <div className="orbit orbitOne" />
      <div className="orbit orbitTwo" />
      <div className="orbit orbitThree" />

      <div className="jarvisOrb">
        <div className="orbCorona" />
        <div className="orbHalo orbHaloOuter" />
        <div className="orbHalo orbHaloMid" />
        <div className="orbHalo orbHaloInner" />
        <div className="orbSurface" />
        <div className="orbSpecular" />
        <div className="orbParticles" />
        <div className="orbLabel">JARVIS</div>
      </div>
    </div>
  );
}
