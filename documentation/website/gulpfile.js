const gulp       = require('gulp');
const pug        = require('gulp-pug');
const sass       = require('gulp-sass')(require('sass'));
const markdown   = require('gulp-markdown-it');
const rename     = require('gulp-rename');
const browserSync = require('browser-sync').create();

const DOCS   = '../docs';
const PUBLIC = '../public';

function styles() {
    return gulp.src('src/styles/main.scss')
        .pipe(sass({ outputStyle: 'compressed' }).on('error', sass.logError))
        .pipe(gulp.dest(`${PUBLIC}/css`))
        .pipe(browserSync.stream());
}

function pages() {
    return gulp.src(`${DOCS}/**/*.md`)
        .pipe(markdown())
        .pipe(rename({ extname: '.html' }))
        .pipe(gulp.dest(PUBLIC))
        .pipe(browserSync.stream());
}

function serve() {
    browserSync.init({ server: { baseDir: PUBLIC } });
    gulp.watch('src/styles/**/*.scss', styles);
    gulp.watch(`${DOCS}/**/*.md`, pages);
}

exports.styles  = styles;
exports.pages   = pages;
exports.build   = gulp.parallel(styles, pages);
exports.default = gulp.series(gulp.parallel(styles, pages), serve);
