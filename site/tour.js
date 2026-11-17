const gallery = document.querySelector('.tour-gallery');
const controls = gallery.querySelector('.tour-controls');
const choices = [...gallery.querySelectorAll('.tour-picker button')];
const slides = choices.map((choice) => document.getElementById(choice.getAttribute('aria-controls')));
const position = document.getElementById('tour-position');
let current = 0;

function show(index, updateLink = false) {
  const imageHadFocus = slides[current].contains(document.activeElement);
  current = (index + slides.length) % slides.length;
  slides.forEach((slide, i) => {
    slide.hidden = i !== current;
    choices[i].setAttribute('aria-pressed', String(i === current));
  });
  position.textContent = `${current + 1} / ${slides.length}`;
  if (updateLink) history.replaceState(null, '', `#${slides[current].id}`);
  if (imageHadFocus) slides[current].querySelector('.tour-shot').focus({ preventScroll: true });
}

choices.forEach((choice, i) => choice.addEventListener('click', () => show(i, true)));
document.getElementById('tour-previous').addEventListener('click', () => show(current - 1, true));
document.getElementById('tour-next').addEventListener('click', () => show(current + 1, true));
gallery.addEventListener('keydown', (event) => {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
  event.preventDefault();
  show(current + (event.key === 'ArrowRight' ? 1 : -1), true);
});
function showLinkedSlide() {
  const linked = slides.findIndex((slide) => '#' + slide.id === location.hash);
  show(linked < 0 ? 0 : linked);
}
window.addEventListener('hashchange', showLinkedSlide);
showLinkedSlide();
controls.hidden = false;
