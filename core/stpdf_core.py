# <STPDF convert scans to pdf>
# Copyright (C) <2019>  <Alexandre Cortegaça>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

# import the necessary packages
import os
import time
import sys
import shutil
import pickle
import logging
import locale
import psutil
import math
from PIL import Image
from pytesseract import image_to_osd, Output
from multiprocessing.connection import Listener, Client
import gettext

from pytesseract.pytesseract import TesseractNotFoundError

###########################################################
#                                                         #
#  STPDFCore(str source, str dest, **kwargs)              #
#   - Verifies the paths and optional arguments provided  #
#   - Gathers all image paths and passes them onto        #
#       STPDFConverter(list image_path, **kwargs)         #
#                                                         #
###########################################################


class STPDFCore:
    """docstring for STPDFCore."""

    def __init__(self, source, dest, **kwargs):
        self.kwargs = kwargs
        self.source = source
        self.dest = dest
        self.deskew = kwargs.get("deskew", False)
        self.installed_lang = kwargs.get("lang", "en")
        self.make_pdf = kwargs.get("make_pdf", True)
        self.save_files = kwargs.get("save_files", False)
        self.log_level = kwargs.get("log_level", "info")
        self.loading_process = kwargs.get("loading_process", "lazy")
        self.resize = kwargs.get("resize", 0)
        # TODO: switch to True
        batch_process, batch_split = kwargs.get("batch_split", (False, 50))
        self.batch_process = batch_process
        self.batch_split = batch_split
        split, at = kwargs.get("split", (False, 0))
        self.split = split
        self.split_at = at
        # Resize is working but is not being passed neither by the cli or the gui
        self.image_paths = []
        self.msg_queue = []
        self.max_mem_usage = self.define_max_memory_usage_until_exception()
        self.proc = psutil.Process(os.getpid())
        self.file_number = 0
        self.file_counter = 0
        # Check how many files to copy
        for __, __, files in os.walk(self.source):
            self.file_number += len(files)
        self.one_percent_files = self.file_number / 100
        # Install language
        if self.installed_lang == "en":
            gettext.install("stpdf-core")
        else:
            modl = "%s_converter" % self.installed_lang
            current_locale, encoding = locale.getdefaultlocale()
            cl = current_locale.split("_")
            if self.installed_lang != cl[0]:
                current_locale = "%s_%s" % (self.installed_lang,
                                            self.installed_lang.upper())
            lang = gettext.translation(modl,
                                       "locale",
                                       [current_locale])
            lang.install()
        self.set_up_logger()

    # This should be removed in the future as for now
    # it is a failsafe mechanism for the users who try to
    # forcibly process more files at the same time
    # regardlessly of the system's specs
    def define_max_memory_usage_until_exception(self):
        mem_values = dict(psutil.virtual_memory()._asdict())
        # i'm using available memory
        # because some of it is cache and can be overwritten
        # however to avoid system hangs i subtract shared memory
        # if it has less digits than available else fallback
        # to free memory that should be lower but still work
        avail_digits = int(math.log10(mem_values["available"]))
        shared_digits = int(math.log10(mem_values["shared"]))
        if shared_digits < avail_digits:
            return int(mem_values["available"] - mem_values["shared"])
        else:
            return int(mem_values["free"])

    # sets up console logger, independent of the GUI/CLI
    def set_up_logger(self):
        print("setting up core logger")
        # switch PIL logger to errors only
        # logging.getLogger("PIL").setLevel(logging.ERROR)
        # set up core logger
        l_level = self.log_level
        n_level = getattr(logging, l_level.upper(), 20)
        if n_level == 20 and l_level.upper() != "INFO":
            sys.stdout.write("%s: %s\n" % (_("Invalid log level"), l_level))
        # Console logger
        formatter = logging.Formatter("%(name)s - %(levelname)s: %(message)s")
        self.logger = logging.getLogger("STPDF.Core")
        self.logger.setLevel(n_level)
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        ch.setLevel(n_level)
        self.logger.addHandler(ch)
        msg = "%s: %s" % (_("Core logger is set with log level"), l_level)
        self.logger.info(msg)

    # Gathers all the paths of images with known extensions
    def gather_images(self):
        known_extensions = ["JPG", "PNG"]
        yield _("Starting image gathering") + "\n"
        yield "%s: %i\n" % (_("Files Found"), self.file_number)
        for root, __, files in os.walk(self.source, topdown=False):
            for file in files:
                self.file_counter += 1
                if(round(self.file_counter % self.one_percent_files, 1) == 0.0):
                    msg = "%i / %i %s.\n" % (self.file_counter,
                                             self.file_number,
                                             _("gathered"))
                    self.logger.debug(msg)
                    yield msg
                extension = os.path.splitext(file)[1][1:].upper()
                source_path = os.path.join(root, file)
                if extension in known_extensions:
                        self.image_paths.append(source_path)
        self.file_number = self.file_counter
        self.one_percent_files = self.file_number / 100
        self.file_counter = 0
        yield _("Gathering done") + "\n"

    def run_converter(self):
        if not self.save_files and not self.make_pdf:
            yield _("Nothing to do, neither save files or make pdf is selected") + "\n"
        else:
            for line in self.gather_images():
                yield line
            if self.batch_process is False:
                print("batch_process is False")
                converter = STPDFConverter(self.image_paths, self.dest, **self.kwargs)
                print("converter set to",converter)
                if self.loading_process == "eager":
                    print("loading is eager")
                    for line in converter.process_images_eager():
                        if self.proc.memory_info().rss >= self.max_mem_usage:
                            raise MemoryError("Exceeding %i bytes limit" % self.max_mem_usage)
                        yield line
                else:
                    print("loading is lazy")
                    try:
                        print
                        for img in converter.process_images_lazy():
                            print("img", img)
                    except Exception as e:
                        print(e)
                        yield e
                    
            else:
                print("batch_process is True")
                sa = self.batch_split
                sets_list = [self.image_paths[i * sa:(i + 1) * sa] for i in range((len(self.image_paths) + sa - 1) // sa)]
                print(sets_list)
                yield "0"
            yield _("Finished")


###########################################################
#                                                         #
#  STPDFConverter(list image_paths, **kwargs)             #
#   - Processes the images provided in the list, inherits #
#      kwargs from STPDFCore                              #
#   - Does not verify if the provided optional kwargs are #
#      invalid, that is the responsibility of the caller  #
#                                                         #
###########################################################


class STPDFConverter:

    def __init__(self, image_paths, dest, **kwargs):
        self.image_paths = image_paths
        self.dest = dest
        self.deskew = kwargs.get("deskew", False)
        self.resolution = kwargs.get("resolution", 90.0)
        self.installed_lang = kwargs.get("lang", "en")
        self.make_pdf = kwargs.get("make_pdf", True)
        self.save_files = kwargs.get("save_files", False)
        self.log_level = kwargs.get("log_level", "info")
        self.resize = kwargs.get("resize", 0)
        self.file_number = len(image_paths)
        self.one_percent_files = self.file_number / 100
        self.file_counter = 0
        self.set_up_logger()

    # set up converter logger, only logs debug messages
    # all other messages should be yielded to the caller
    # independent of STPDFCore and GUI/CLI
    def set_up_logger(self):
        l_level = self.log_level
        n_level = getattr(logging, l_level.upper(), 20)
        if n_level == 20 and l_level.upper() != "INFO":
            sys.stdout.write("%s: %s\n" % (_("Invalid log level"), l_level))
        # Console logger
        formatter = logging.Formatter("%(name)s - %(levelname)s: %(message)s")
        self.logger = logging.getLogger("STPDF.Core.Converter")
        self.logger.setLevel(n_level)
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        ch.setLevel(n_level)
        self.logger.addHandler(ch)
        msg = "%s: %s" % (_("Converter logger is set with log level"), l_level)
        self.logger.debug(msg)

    # returns progress string
    def yield_progress_status(self, action):
        if(round(self.file_counter % self.one_percent_files, 1) == 0.0):
            msg = "%i / %i %s.\n" % (self.file_counter,
                                     self.file_number,
                                     action)
            return msg
        else:
            return False

    def log_action_msg(self, action, ref_object=None):
        msg = ""
        if ref_object is None:
            msg = "%s" % (action)
        else:
            msg = "%s: %s" % (action, ref_object)
        self.logger.debug(msg)

    # Processes the images directly into memory
    # and creates a pdf out of them
    def process_images_eager(self):
        yield _("Starting image processing") + "\n"
        images = []
        for img_p in self.image_paths:
            self.file_counter += 1
            print_progress = self.yield_progress_status(_("processed"))
            if print_progress is not False:
                yield print_progress
            dest_p = os.path.join(self.dest, os.path.basename(img_p))
            try:
                self.verify_image(img_p)
            except Exception as e:
                self.log_action_msg(_("Failed to verify image"), img_p)
                self.log_action_msg(_("Skipping image"))
                continue
            img = self.process_image(img_p)
            images.append(img)
        first_img = images.pop(0)
        name = os.path.join(self.dest, "%i.pdf" % self.file_counter)
        while os.path.isfile(name):
            self.file_counter += 1
            name = os.path.join(self.dest, "%i.pdf" % self.file_counter)
        first_img.save(name, "PDF", resolution=self.resolution, save_all=True,
                       append_images=images)
        yield _("Processing done") + "\n"

    # "lazy-loads" the images, if make_pdf is True
    # then it uses the image generator to append the images one by one
    # else just iterates trough the generator.
    # msg_queue is a list provided by caller to be passed onto the generator,
    # the caller should "use" the message and pop it from the list
    def process_images_lazy(self):
        # msg = _("Starting image processing") + "\n"
        # msg_queue.append(msg)
        # Check if images are to be put onto a pdf or just processed,
        # it does not check save_files value, responsibility of the caller....
        if self.make_pdf:
            first_img = self.process_image(self.image_paths.pop(0))
            name = os.path.join(self.dest, "%i.pdf" % self.file_counter)
            while os.path.isfile(name):
                self.file_counter += 1
                name = os.path.join(self.dest, "%i.pdf" % self.file_counter)
            first_img.save(name, "PDF", resolution=self.resolution, save_all=True,
                           append_images=self.processed_images_generator())
        else:
            # we don't really care about the images here
            # since they are already processed and make_pdf is false
            for img in self.processed_images_generator():
                yield img
        # msg = _("Processing done") + "\n"
        # msg_queue.append(msg)

    # A generator for "lazy-loading" the images
    # instead of trying to load them all at once
    def processed_images_generator(self):
        print("generating processed image")
        for img_p in self.image_paths:
            # print_progress = self.yield_progress_status(_("processed"))
            # if print_progress is not False:
            #     msg_queue.append(print_progress)
            # Verify the image before trying to process it
            # on exception skip image
            try:
                print("verifying image")
                verified = self.verify_image(img_p)
                if verified is True:
                    yield self.process_image(img_p)
                else:
                    raise verified
            except Exception as e:
                self.log_action_msg(_("Failed to verify image"), img_p)
                self.log_action_msg(_("Skipping image"))
                continue

    # Reads image in binary data passes data onto
    # Image.open() and processes image trough all the available methods
    # returns processed image
    def process_image(self, img_path):
        dest_p = os.path.join(self.dest, os.path.basename(img_path))
        print("process_image(): reading image")
        with open(img_path, "rb") as fp:
            with Image.open(fp) as img:
                print("loading image")
                img.load()
                # if there is no processing to be done just return the loaded img
                if not (self.deskew or self.resize or self.save_files):
                    print("returning image", img)
                    return img
                if self.deskew:
                    try:
                        d_img = self.deskew_image(img)
                        img = d_img
                    except Exception as e:
                        self.log_action_msg(_("Failed to deskew image"), img)
                        pass
                if self.resize:
                    img = self.resize_image(img)
                if self.save_files:
                    img.save(dest_p)
                print("returning image", img)                
                return img

    # Tries to verify the images using PILLOW's image.verify()
    # returns any exception occured, image should be skipped if
    # failed to verify, the caller is responsible for that
    def verify_image(self, img_p):
        print("verify_image(): reading image for verification", img_p)
        with open(img_p, "rb") as fp:
            self.log_action_msg(_("Verifying image"), img_p)
            # read the file into Pil's Image.open method
            print("verify_image(): reading image with PIL")
            with Image.open(fp) as img:
                print("trying to verify")
                # Try to verify the file or skip it
                try:
                    img.verify()
                    return True
                except Exception as e:
                    return e

    # resizes the image based on a percentage
    def resize_image(self, img):
        self.log_action_msg(_("Resizing image"), img)
        size = (img.size[0] / self.resize, img.size[1] / self.resize)
        img.thumbnail(size, Image.ANTIALIAS)
        return img

    # Deskews *(Fixes alignment) of image using tesseract-OCR
    # BUG: Some images get flipped sideways
    def deskew_image(self, img):
        self.log_action_msg(_("Deskewing image"), img)
        try:
            rotate = image_to_osd(img, output_type=Output.DICT)["rotate"]
            # This tells it to use the
            # highest quality interpolation algorithm that it has available,
            # and to expand the image to encompass the full rotated size
            # instead of cropping.
            # The documentation does not say what color
            # the background will be filled with.
            # https://stackoverflow.com/a/17822099
            img = img.rotate(-rotate, resample=Image.BICUBIC, expand=True)
        # sometimes an error can occur with tesseract reading the image
        # maybe there is not enough text or dpi is not set
        # this need to be handled
        except Exception as e:
            self.logger.error(e)
            raise e
        return img
