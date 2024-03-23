val = 0b0110

print("Val %s" % val)

for i in range(0, 4):
    mask = 1 << i
    print("Mask %s" % mask)
    val_maskee = val & mask
    print("Val masquee %s" % val_maskee)
    val_bool = val_maskee > 0
    print("Val bool %s" % val_bool)
