# import the necessary packages
import os, shutil
from PIL import Image
from pytesseract import image_to_osd, Output

class Converter(object):
    """docstring for Converter."""

    def __init__(self,source,dest,split=(True,1),deskew=False, resolution=90.0):
        super(Converter, self).__init__()
        self.source = source
        self.dest = dest
        self.deskew = deskew
        self.resolution = resolution
        self.images = {}
        self.counter = 0
        split, at = split
        self.split = split
        self.split_at = at
        self.file_number = 0
        # Check how many files to copy
        for root,dirs,files in os.walk(self.source):
            self.file_number += len(files)


    def __del__(self):
        for handle in self.images:
            self.images[handle].close()

    # checks how many files are there to copy over
    def verify_copy_size(self):
        if self.file_number >= 1000:
            yield _("Found many file to copy, this might take a while")
        else:
            for line in self.copy_images():
                yield line


    def copy_images(self):
        yield "%s: %i" % (_("Files to copy"), self.file_number)
        for root, dirs, files in os.walk(self.source, topdown=False):
            for file in files:
                extension = os.path.splitext(file)[1][1:].upper()
                source_path = os.path.join(root, file)
                destination_dir = self.dest
                if extension.endswith("PNG") or extension.endswith("JPG"):
                    # Rotate the images first if deskew is true
                    img = Image.open(source_path)
                    if self.deskew:
                        # TODO: If the images is to be deskewed it could be saved directly
                        # in the des dir and continue the loop
                        deskew_image(img,destination_dir,file)
                    else:
                        self.images[source_path] = img
                    # Check destination and copy files over
                    if not os.path.exists(destination_dir):
                        os.mkdir(destination_dir)
                    else:
                        file_name = str(file) + "." + extension.lower()

                    destination_file = os.path.join(destination_dir, file_name)
                    if not os.path.exists(destination_file):
                        shutil.copy2(source_path, destination_file)

    def deskew_image(self, img, dest, file):
        dest_path = os.path.join(root, file)
        rotate = image_to_osd(img, output_type=Output.DICT)["rotate"]
        # This tells it to use the highest quality interpolation algorithm that it has available,
        # and to expand the image to encompass the full rotated size instead of cropping.
        # The documentation does not say what color the background will be filled with.
        # https://stackoverflow.com/a/17822099
        img.rotate(-rotate,resample=Image.BICUBIC, expand=True).save(dest_path)

    def make_pdf(self):
        # Get all image handles
        if self.split:
            sa = self.split_at
            yield "%s %i" %  (_("Creating multiple PDFs splitting by:"), sa)
            image_handles = [self.images[image] for image in self.images]
            if len(image_handles) > sa:
                # Mom's spaghetti ahead
                image_handles = [image_handles[i * sa:(i + 1) * sa] for i in range((len(image_handles) + sa - 1) // sa)]
                for list in image_handles:
                    first = list[0]
                    list.pop[0]
                    first.save("1.pdf", "PDF", resolution=90.0, save_all=True, append_images=image_handles)
        else:
            yield _("Creating a single pdf")
            # Remove the first and store it in a variable
            first = image_handles[0]
            image_handles.pop(0)
            # Save the first image as pdf and append the others
            first.save("1.pdf", "PDF", resolution=90.0, save_all=True, append_images=image_handles)