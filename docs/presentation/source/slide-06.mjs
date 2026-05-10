export async function slide06(presentation, ctx) {
  const slide = presentation.slides.add();
  await ctx.addImage(slide, {
    path: new URL("../slides/slide-06-provider-proof.png", import.meta.url).pathname,
    x: 0,
    y: 0,
    w: ctx.W,
    h: ctx.H,
    fit: "cover",
    alt: "Every provider does visible work",
  });
  return slide;
}
